"""Registra todos los deployments de Prefect en el servidor."""

from prefect import deploy

from orchestration.deployments.etl_deployments import etl_deployments
from orchestration.deployments.health_deployments import health_deployments
from shared.settings import settings


def deploy_all_flows():
    print("Registering deployments...")

    all_deployments = health_deployments + etl_deployments

    deploy(*all_deployments, work_pool_name=settings.PREFECT_WORK_POOL_NAME)

    print(f"Se han registrado {len(all_deployments)} despliegues exitosamente.")


if __name__ == "__main__":
    deploy_all_flows()
