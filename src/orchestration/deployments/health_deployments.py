"""Deployment del health check.

Sin schedule: se dispara desde la UI cuando hay que verificar que el worker, la
base y la API del origen responden. No lleva sufijo `-manual` porque no hay una
variante programada de la que distinguirlo — ver la nota sobre deployments en
`etl_deployments.py`.
"""

from orchestration.flows.health_flows import health_check

health_deployments = [
    health_check.from_source(
        source=".",
        entrypoint="src/orchestration/flows/health_flows.py:health_check",
    ).to_deployment(
        name="health-check",
        tags=["health", "infra"],
    ),
]
