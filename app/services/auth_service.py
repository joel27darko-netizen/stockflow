import logging
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class AuthError(Exception):
    pass


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = UserRepository(db)
        self.audit = AuditService(db)

    def register_user(self, data: UserCreate, created_by: Optional[int] = None) -> User:
        if self.repo.get_by_username(data.username):
            raise AuthError("Username already exists.")
        if self.repo.get_by_email(data.email):
            raise AuthError("Email already registered.")

        user = User(
            username=data.username,
            full_name=data.full_name,
            email=data.email,
            hashed_password=hash_password(data.password),
            role=data.role,
            must_change_password=True,  # admin-set passwords must be changed on first login
        )
        user = self.repo.create(user)
        self.audit.log(created_by, "CREATE_USER", "User", user.id, f"username={user.username}")
        logger.info("New user registered: %s (role=%s)", user.username, user.role)
        return user

    def authenticate(self, username: str, password: str) -> Optional[User]:
        user = self.repo.get_by_username(username)
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def login(self, username: str, password: str, remember_me: bool = False) -> str:
        user = self.authenticate(username, password)
        if not user:
            self.audit.log(None, "LOGIN_FAILED", "User", None, f"username={username}")
            raise AuthError("Invalid username or password.")

        # "Remember me" extends the session token lifetime from the
        # default 8 hours to 30 days, rather than being a purely
        # cosmetic checkbox — the cookie's max_age is set to match in
        # the router.
        expires_delta = timedelta(days=30) if remember_me else None
        token = create_access_token(
            {"sub": user.username, "uid": user.id, "role": user.role.value},
            expires_delta=expires_delta,
        )
        self.audit.log(user.id, "LOGIN_SUCCESS", "User", user.id, f"remember_me={remember_me}")
        logger.info("User logged in: %s (remember_me=%s)", user.username, remember_me)
        return token

    def set_active_status(self, user_id: int, is_active: bool, acting_user_id: int) -> User:
        """Deactivate or reactivate a user. Prevents an admin from deactivating themselves."""
        user = self.repo.get(user_id)
        if not user:
            raise AuthError("User not found.")
        if user_id == acting_user_id and not is_active:
            raise AuthError("You cannot deactivate your own account.")
        user.is_active = is_active
        user = self.repo.update(user)
        action = "DEACTIVATE_USER" if not is_active else "REACTIVATE_USER"
        self.audit.log(acting_user_id, action, "User", user.id, f"username={user.username}")
        logger.info("%s: %s", action, user.username)
        return user

    def delete_user(self, user_id: int, acting_user_id: int) -> None:
        """
        Permanently deletes a user. Only allowed if the user has no
        associated transactions (deleting them would break the audit
        trail / transaction ledger's foreign key integrity). Use
        set_active_status() to deactivate instead in that case.
        """
        user = self.repo.get(user_id)
        if not user:
            raise AuthError("User not found.")
        if user_id == acting_user_id:
            raise AuthError("You cannot delete your own account.")
        if user.transactions:
            raise AuthError(
                "This user has transaction history and cannot be permanently deleted. "
                "Deactivate the account instead to preserve the audit trail."
            )
        username = user.username
        self.repo.delete(user)
        self.audit.log(acting_user_id, "DELETE_USER", "User", user_id, f"username={username}")
        logger.info("User deleted: %s", username)

    def change_password(self, user_id: int, current_password: str, new_password: str) -> User:
        """
        Lets a logged-in user set a new password themselves — used both
        for the forced first-login change and for a voluntary change
        later. Requires re-entering the current password as a
        confirmation step (standard practice: a stolen/left-open
        session shouldn't be enough on its own to take over the
        account by silently changing the password).
        """
        user = self.repo.get(user_id)
        if not user:
            raise AuthError("User not found.")
        if not verify_password(current_password, user.hashed_password):
            raise AuthError("Current password is incorrect.")
        if len(new_password) < 6:
            raise AuthError("New password must be at least 6 characters long.")
        if verify_password(new_password, user.hashed_password):
            raise AuthError("New password must be different from your current password.")

        user.hashed_password = hash_password(new_password)
        user.must_change_password = False
        user = self.repo.update(user)
        self.audit.log(user_id, "CHANGE_PASSWORD", "User", user.id, f"username={user.username}")
        logger.info("Password changed for user: %s", user.username)
        return user

    def ensure_default_admin(self) -> None:
        """Bootstrap a default admin account on first run, if none exists."""
        if not self.repo.get_by_username("admin"):
            admin = User(
                username="admin",
                full_name="System Administrator",
                email="admin@stockflow.local",
                hashed_password=hash_password("Admin@123"),
                role="admin",
                must_change_password=True,
            )
            self.repo.create(admin)
            logger.warning(
                "Default admin account created (username=admin / password=Admin@123). "
                "Change this password immediately in a real deployment."
            )
