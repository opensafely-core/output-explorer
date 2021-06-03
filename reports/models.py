import re
from uuid import uuid4

import structlog
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django_extensions.db.fields import AutoSlugField
from environs import Env

from .github import GithubAPIException, GithubReport


env = Env()
logger = structlog.getLogger()


def validate_html_filename(value):
    if not re.match(r".*\.html?$", value):
        raise ValidationError(
            _("%(value)s must be an html file"),
            params={"value": value},
        )


class AutoPopulatingCharField(models.CharField):
    def __init__(self, *args, populate_from=None, **kwargs):
        if populate_from:
            self._populate_from = populate_from
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self._populate_from:
            kwargs["populate_from"] = self._populate_from
        return name, path, args, kwargs

    def clean(self, value, model_instance):
        if not value:
            if self._populate_from:
                value = getattr(model_instance, self._populate_from)
        return super().clean(value, model_instance)


class PopulatedCategoryManager(models.Manager):
    """
    Manager that returns only Categories that have at least one associated Report
    """

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .annotate(count=models.Count("reports"))
            .filter(count__gt=0)
        ).order_by("name")

    def for_user(self, user):
        report_category_ids = set(
            Report.objects.for_user(user).values_list("category_id", flat=True)
        )
        return self.get_queryset().filter(id__in=report_category_ids).order_by("name")


class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    objects = models.Manager()
    populated = PopulatedCategoryManager()

    class Meta:
        verbose_name_plural = "categories"
        ordering = ("name",)

    def __str__(self):
        return self.name


class ReportManager(models.Manager):
    """
    Manager that can returns only Reports that a particular user has access to
    """

    def for_user(self, user):
        queryset = self.get_queryset()
        if user.has_perm("reports.view_draft"):
            return queryset
        return queryset.filter(is_draft=False)


class Report(models.Model):
    """
    A report retrieved from an OpenSAFELY github repo
    Currently allows for single HTML report files only
    """

    objects = ReportManager()
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        help_text="Report category; used for navigation",
        related_name="reports",
    )
    menu_name = AutoPopulatingCharField(
        max_length=60,
        populate_from="title",
        help_text="A short name to display in the side nav",
    )
    repo = models.CharField(
        max_length=255, help_text="Name of the OpenSAFELY repo (case insensitive)"
    )
    branch = models.CharField(max_length=255, default="main")
    report_html_file_path = models.CharField(
        max_length=255,
        help_text="Path to the report html file within the repo",
        validators=[validate_html_filename],
    )
    slug = AutoSlugField(max_length=100, populate_from=["title"], unique=True)

    # front matter fields
    authors = models.TextField(null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField(
        help_text="Short description to display before rendered report and in meta tags",
    )
    publication_date = models.DateField(help_text="Date published")
    last_updated = models.DateField(
        null=True,
        blank=True,
        help_text="File last modified date; autopopulated from GitHub",
    )
    cache_token = models.UUIDField(default=uuid4)
    # Flag to remember if this report needed to use the git blob method (see github.py),
    # to avoid re-calling the contents endpoint if we know it will fail
    use_git_blob = models.BooleanField(default=False)
    is_draft = models.BooleanField(
        default=False,
        help_text="Draft reports are only visible by a logged in user with relevant permissions",
    )

    contact_email = models.EmailField(default="team@opensafely.org")

    class Meta:
        ordering = ("menu_name",)
        permissions = [
            ("view_draft", "Can view draft reports"),
        ]

    def __str__(self):
        return self.slug

    def refresh_cache_token(self, refresh_http_cache=True, commit=True):
        """Refresh cache token to invalidate http cache and clear request cache for github requests related to this repo"""
        self.cache_token = uuid4()
        if refresh_http_cache:
            GithubReport(self).clear_cache()
        if commit:
            self.save()

    @property
    def meta_title(self):
        return f"{self.title} | OpenSAFELY: Reports"

    def clean(self):
        """Validate the repo, branch and report file path on save"""
        # GITHUB_VALIDATION env var can optionally be set to False to skip this validation in tests
        if env.bool("GITHUB_VALIDATION", True):
            # Disable caching to fetch the repo and contents.  If this is a new report file in
            # an existing folder, we don't want to use a previously cached request
            github_report = GithubReport(self, use_cache=False)
            try:
                # noinspection PyStatementEffect
                github_report.repo
            except GithubAPIException:
                raise ValidationError(
                    {"repo": _("'%(repo)s' could not be found") % {"repo": self.repo}}
                )

            try:
                github_report.get_parent_contents()
            except GithubAPIException as error:
                # This happens if either the branch or the report file's parent path is invalid
                raise ValidationError(
                    _("Error fetching report file: %(error_message)s"),
                    params={"error_message": str(error)},
                )

            if not any(github_report.matching_report_file_from_parent_contents()):
                raise ValidationError(
                    {
                        "report_html_file_path": _(
                            "File could not be found (branch %(branch)s)"
                        )
                        % {"branch": self.branch}
                    }
                )
        super().clean()

    @classmethod
    def from_db(cls, db, field_names, values):
        """Extended from_db method to store original field values on the instance"""
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = dict(zip(field_names, values))
        return instance

    def save(self, *args, **kwargs):
        # if updating an existing instance, check fields changed and refresh cache if required
        # instances just created (in tests/shell) will not have called `from_db`
        if hasattr(self, "_loaded_values") and not self._state.adding:
            requests_cache_fields = {"repo", "branch", "report_html_file_path"}
            # exclude fields that are autopopulated or irrelevant for http caching from the check
            exclude_fields = {
                "id",
                "slug",
                "cache_token",
                "last_updated",
                "use_git_blob",
                "is_draft",
            }
            all_field_keys = self._loaded_values.keys()
            http_cache_fields = (
                set(all_field_keys) - requests_cache_fields - exclude_fields
            )
            if any(
                getattr(self, field) != self._loaded_values[field]
                for field in requests_cache_fields
            ):
                logger.info(
                    "Source repo field(s) updated; refreshing cache token and clearing requests cache"
                )
                self.refresh_cache_token(commit=False)
            elif any(
                getattr(self, field) != self._loaded_values[field]
                for field in http_cache_fields
            ):
                logger.info("Non-repo field(s) updated; refreshing cache token only")
                self.refresh_cache_token(refresh_http_cache=False, commit=False)

        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("reports:report_view", args=(self.slug, self.cache_token))
