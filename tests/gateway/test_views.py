import pytest
from django.urls import reverse
from model_bakery import baker

from gateway.models import Organisation, User


@pytest.mark.django_db
def test_organisation_view_permissions(client):
    """Test organisation page can only be accessed by users with that org"""
    organisation1 = baker.make(Organisation, code="T1", name="test1")
    organisation2 = baker.make(Organisation, code="T2", name="test2")
    user = User.objects.create_user(username="test", password="test")
    user.organisations.add(organisation1)

    # login required
    response = client.get(
        reverse("gateway:organisation_detail", args=(organisation1.code,))
    )
    assert response.status_code == 302
    assert response.url == reverse("gateway:login") + "?next=/organisation/T1"

    client.login(username="test", password="test")
    # user has access to organisation1
    response = client.get(
        reverse("gateway:organisation_detail", args=(organisation1.code,))
    )
    assert response.status_code == 200

    # user does not have access to organisation2
    response = client.get(
        reverse("gateway:organisation_detail", args=(organisation2.code,))
    )
    assert response.status_code == 403