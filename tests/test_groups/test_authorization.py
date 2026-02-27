"""Tests for authorization policy."""

from g2.groups.authorization import AuthContext, AuthorizationPolicy


def _main_policy() -> AuthorizationPolicy:
    return AuthorizationPolicy(AuthContext(source_group="main", is_main=True))


def _non_main_policy(group: str = "project-a") -> AuthorizationPolicy:
    return AuthorizationPolicy(AuthContext(source_group=group, is_main=False))


class TestMainGroupAuth:
    def test_can_send_to_any_group(self):
        policy = _main_policy()
        assert policy.can_send_message("main") is True
        assert policy.can_send_message("other-group") is True

    def test_can_schedule_for_any_group(self):
        policy = _main_policy()
        assert policy.can_schedule_task("main") is True
        assert policy.can_schedule_task("other-group") is True

    def test_can_manage_any_task(self):
        policy = _main_policy()
        assert policy.can_manage_task("main") is True
        assert policy.can_manage_task("other-group") is True

    def test_can_register_group(self):
        assert _main_policy().can_register_group() is True

    def test_can_refresh_groups(self):
        assert _main_policy().can_refresh_groups() is True

    def test_can_manage_any_session(self):
        policy = _main_policy()
        assert policy.can_manage_session("main") is True
        assert policy.can_manage_session("other-group") is True


class TestNonMainGroupAuth:
    def test_can_send_to_own_group(self):
        policy = _non_main_policy("project-a")
        assert policy.can_send_message("project-a") is True

    def test_cannot_send_to_other_group(self):
        policy = _non_main_policy("project-a")
        assert policy.can_send_message("project-b") is False

    def test_can_schedule_for_own_group(self):
        policy = _non_main_policy("project-a")
        assert policy.can_schedule_task("project-a") is True

    def test_cannot_schedule_for_other_group(self):
        policy = _non_main_policy("project-a")
        assert policy.can_schedule_task("project-b") is False

    def test_can_manage_own_task(self):
        policy = _non_main_policy("project-a")
        assert policy.can_manage_task("project-a") is True

    def test_cannot_manage_other_task(self):
        policy = _non_main_policy("project-a")
        assert policy.can_manage_task("project-b") is False

    def test_cannot_register_group(self):
        assert _non_main_policy().can_register_group() is False

    def test_cannot_refresh_groups(self):
        assert _non_main_policy().can_refresh_groups() is False

    def test_can_manage_own_session(self):
        policy = _non_main_policy("project-a")
        assert policy.can_manage_session("project-a") is True

    def test_cannot_manage_other_session(self):
        policy = _non_main_policy("project-a")
        assert policy.can_manage_session("project-b") is False


class TestAuthContext:
    def test_source_group_property(self):
        policy = _non_main_policy("my-group")
        assert policy.source_group == "my-group"

    def test_is_main_property(self):
        assert _main_policy().is_main is True
        assert _non_main_policy().is_main is False
