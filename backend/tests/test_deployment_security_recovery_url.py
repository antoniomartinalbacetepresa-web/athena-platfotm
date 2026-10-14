from app.services.deployment_security_readiness_service import (
    DeploymentSecurityReadinessService,
)


def test_recovery_public_url_requires_absolute_https_endpoint() -> None:
    valid = (
        "https://athena.example/reset",
        "https://athena.example:8443/account/recovery",
    )
    invalid = (
        "",
        "https://",
        "http://athena.example/reset",
        "https:///reset",
        "https://user:secret@athena.example/reset",
        "https://athena.example:99999/reset",
    )

    for value in valid:
        assert DeploymentSecurityReadinessService._valid_public_recovery_url(value) is True

    for value in invalid:
        assert DeploymentSecurityReadinessService._valid_public_recovery_url(value) is False
