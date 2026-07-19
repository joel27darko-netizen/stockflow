import pytest

from app.schemas.user import UserCreate
from app.models.user import UserRole
from app.services.auth_service import AuthService, AuthError


def test_register_and_authenticate(db_session):
    service = AuthService(db_session)
    user = service.register_user(
        UserCreate(username="jdoe", full_name="Jane Doe", email="jane@example.com",
                    password="secret123", role=UserRole.STAFF)
    )
    assert user.id is not None
    assert user.username == "jdoe"

    authenticated = service.authenticate("jdoe", "secret123")
    assert authenticated is not None
    assert authenticated.id == user.id


def test_authenticate_wrong_password_fails(db_session):
    service = AuthService(db_session)
    service.register_user(
        UserCreate(username="jdoe", full_name="Jane Doe", email="jane@example.com",
                    password="secret123", role=UserRole.STAFF)
    )
    assert service.authenticate("jdoe", "wrongpassword") is None


def test_duplicate_username_rejected(db_session):
    service = AuthService(db_session)
    service.register_user(
        UserCreate(username="jdoe", full_name="Jane Doe", email="jane@example.com",
                    password="secret123", role=UserRole.STAFF)
    )
    with pytest.raises(AuthError):
        service.register_user(
            UserCreate(username="jdoe", full_name="Someone Else", email="other@example.com",
                        password="secret456", role=UserRole.STAFF)
        )


def test_ensure_default_admin_creates_once(db_session):
    service = AuthService(db_session)
    service.ensure_default_admin()
    service.ensure_default_admin()  # should not raise or duplicate
    admins = [u for u in service.repo.list_all() if u.username == "admin"]
    assert len(admins) == 1


def test_new_user_must_change_password_by_default(db_session):
    service = AuthService(db_session)
    user = service.register_user(
        UserCreate(username="jdoe", full_name="Jane Doe", email="jane@example.com",
                    password="secret123", role=UserRole.STAFF)
    )
    assert user.must_change_password is True


def test_change_password_success_clears_flag(db_session):
    service = AuthService(db_session)
    user = service.register_user(
        UserCreate(username="jdoe", full_name="Jane Doe", email="jane@example.com",
                    password="secret123", role=UserRole.STAFF)
    )
    updated = service.change_password(user.id, "secret123", "newpassword456")
    assert updated.must_change_password is False
    assert service.authenticate("jdoe", "newpassword456") is not None
    assert service.authenticate("jdoe", "secret123") is None


def test_change_password_wrong_current_password_rejected(db_session):
    service = AuthService(db_session)
    user = service.register_user(
        UserCreate(username="jdoe", full_name="Jane Doe", email="jane@example.com",
                    password="secret123", role=UserRole.STAFF)
    )
    with pytest.raises(AuthError):
        service.change_password(user.id, "wrongpassword", "newpassword456")


def test_change_password_too_short_rejected(db_session):
    service = AuthService(db_session)
    user = service.register_user(
        UserCreate(username="jdoe", full_name="Jane Doe", email="jane@example.com",
                    password="secret123", role=UserRole.STAFF)
    )
    with pytest.raises(AuthError):
        service.change_password(user.id, "secret123", "abc")


def test_change_password_same_as_current_rejected(db_session):
    service = AuthService(db_session)
    user = service.register_user(
        UserCreate(username="jdoe", full_name="Jane Doe", email="jane@example.com",
                    password="secret123", role=UserRole.STAFF)
    )
    with pytest.raises(AuthError):
        service.change_password(user.id, "secret123", "secret123")
