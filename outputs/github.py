from base64 import b64decode
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup, Tag
from django.utils.safestring import mark_safe
from environs import Env
from github import Github, GithubException


env = Env()


class GitHubOutput:
    def __init__(self, output, repo=None):
        token = env.str("GITHUB_TOKEN", None)
        self.client = Github(token) if token else Github()
        self.output = output
        self._repo = repo

    @property
    def repo(self):
        if self._repo is None:
            self._repo = self.client.get_repo(f"opensafely/{self.output.repo}")
        return self._repo

    def get_parent_contents(self):
        parent_folder = str(Path(self.output.output_html_file_path).parent)
        return self.repo.get_contents(parent_folder, ref=self.output.branch)

    def matching_output_file_from_parent_contents(self):
        output_html_file_name = Path(self.output.output_html_file_path).name
        return (
            content_file
            for content_file in self.get_parent_contents()
            if content_file.name == output_html_file_name
        )

    def get_contents_from_git_blob(self):
        """
        Get all the content files from the parent folder (doesn't download the actual content
        itself, but returns a list of ContentFile objects, from which we can obtain sha for
        the relevant file, retrieve the git blob and return the html contents
        """
        # Find the file in the parent folder whose name matches the output file we want
        matching_content_file = next(self.matching_output_file_from_parent_contents())
        last_updated = matching_content_file.last_modified
        blob = self.repo.get_git_blob(matching_content_file.sha)
        contents = b64decode(blob.content)
        return contents, last_updated

    def get_html(self):
        """
        Fetches an output html file (an exported jupyter notebook) from a github repo based
        on `output`, an Output model instance.
        The notebook html consists of style, body and script tags.  Ignores any script tags.
        Return the style tags and html body content for display in template.
        """
        try:
            contents = self.repo.get_contents(
                self.output.output_html_file_path, ref=self.output.branch
            )
            last_updated = contents.last_modified
            contents = contents.decoded_content

        except GithubException:
            # If the single file was too big (>1Mb), we get an exception.  Get the git blob
            # and retrieve the contents from there instead
            contents, last_updated = self.get_contents_from_git_blob()
        last_updated_date = datetime.strptime(
            last_updated, "%a, %d %b %Y %H:%M:%S %Z"
        ).date()
        if self.output.last_updated != last_updated_date:
            self.output.last_updated = last_updated_date
            self.output.save()

        soup = BeautifulSoup(contents, "html.parser")
        style = soup.find_all("style")
        body = soup.find("body")
        style = [mark_safe(style_item.decode()) for style_item in style]
        contents = "".join(
            [
                content.decode() if isinstance(content, Tag) else content
                for content in body.contents
            ]
        )
        return {"body": mark_safe(contents), "style": style}