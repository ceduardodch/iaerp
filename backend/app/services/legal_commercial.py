import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.models.legal_commercial import (
    AwsConsumptionCut,
    BillingProposal,
    CommercialContract,
    ContractVersion,
)
from app.models.masters import Party
from app.schemas.legal_commercial import (
    AwsConsumptionCutCreate,
    BillingProposalCreate,
    CommercialContractCreate,
    ContractVersionCreate,
)
from app.services import storage

MAX_SIGNED_CONTRACT_BYTES = 10 * 1024 * 1024


async def _customer(session: AsyncSession, context: AuthContext, party_id: uuid.UUID) -> None:
    party = await session.scalar(
        select(Party).where(
            Party.id == party_id, Party.tenant_id == context.tenant_id, Party.active.is_(True)
        )
    )
    if party is None or "CUSTOMER" not in party.roles:
        raise HTTPException(status_code=404, detail="Customer not found")


async def create_contract(
    session: AsyncSession, context: AuthContext, data: CommercialContractCreate
) -> CommercialContract:
    await _customer(session, context, data.party_id)
    entity = CommercialContract(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def create_contract_version(
    session: AsyncSession, context: AuthContext, contract_id: uuid.UUID, data: ContractVersionCreate
) -> ContractVersion:
    contract = await session.scalar(
        select(CommercialContract)
        .where(
            CommercialContract.id == contract_id, CommercialContract.tenant_id == context.tenant_id
        )
        .with_for_update()
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Commercial contract not found")
    latest = await session.scalar(
        select(ContractVersion.version_number)
        .where(
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == context.tenant_id,
        )
        .order_by(ContractVersion.version_number.desc())
        .limit(1)
    )
    entity = ContractVersion(
        tenant_id=context.tenant_id,
        contract_id=contract_id,
        version_number=(latest or 0) + 1,
        **data.model_dump(by_alias=False),
    )
    session.add(entity)
    await session.flush()
    return entity


async def list_contracts(
    session: AsyncSession, context: AuthContext, party_id: uuid.UUID | None = None
) -> list[CommercialContract]:
    statement = select(CommercialContract).where(CommercialContract.tenant_id == context.tenant_id)
    if party_id is not None:
        statement = statement.where(CommercialContract.party_id == party_id)
    return list(await session.scalars(statement.order_by(CommercialContract.created_at.desc())))


async def list_contract_versions(
    session: AsyncSession, context: AuthContext, contract_id: uuid.UUID
) -> list[ContractVersion]:
    await _contract(session, context, contract_id)
    return list(
        await session.scalars(
            select(ContractVersion)
            .where(
                ContractVersion.tenant_id == context.tenant_id,
                ContractVersion.contract_id == contract_id,
            )
            .order_by(ContractVersion.version_number.desc())
        )
    )


async def _contract(
    session: AsyncSession, context: AuthContext, contract_id: uuid.UUID
) -> CommercialContract:
    contract = await session.scalar(
        select(CommercialContract).where(
            CommercialContract.id == contract_id, CommercialContract.tenant_id == context.tenant_id
        )
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="Commercial contract not found")
    return contract


async def upload_signed_contract(
    session: AsyncSession,
    context: AuthContext,
    *,
    contract_id: uuid.UUID,
    version_id: uuid.UUID,
    filename: str | None,
    data: bytes,
) -> ContractVersion:
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="Signed contract must be a PDF")
    if len(data) > MAX_SIGNED_CONTRACT_BYTES:
        raise HTTPException(status_code=413, detail="Signed contract exceeds 10 MB")
    version = await session.scalar(
        select(ContractVersion)
        .where(
            ContractVersion.id == version_id,
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == context.tenant_id,
        )
        .with_for_update()
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Contract version not found")
    if version.status in {"SIGNED", "ACTIVE", "SUPERSEDED"}:
        raise HTTPException(status_code=409, detail="Signed contract version is immutable")
    safe_name = (filename or "contrato-firmado.pdf").replace("/", "_").replace("\\", "_")
    object_key = (
        f"{context.tenant_id}/commercial/contracts/{contract_id}/"
        f"v{version.version_number}/{safe_name}"
    )
    uploaded = await storage.upload_private_object(
        object_key=object_key, data=data, content_type="application/pdf"
    )
    version.signed_artifact_object_key = uploaded.object_key
    version.signed_artifact_sha256 = uploaded.sha256
    version.status = "SIGNED"
    version.signed_at = datetime.now(UTC)
    contract = await _contract(session, context, contract_id)
    contract.status = "SIGNED"
    contract.current_version_id = version.id
    await session.flush()
    return version


async def signed_contract_download(
    session: AsyncSession, context: AuthContext, *, contract_id: uuid.UUID, version_id: uuid.UUID
) -> tuple[str, str]:
    version = await session.scalar(
        select(ContractVersion).where(
            ContractVersion.id == version_id,
            ContractVersion.contract_id == contract_id,
            ContractVersion.tenant_id == context.tenant_id,
        )
    )
    if version is None or not version.signed_artifact_object_key:
        raise HTTPException(status_code=404, detail="Signed contract PDF not found")
    file_name = f"contrato-{contract_id}-v{version.version_number}.pdf"
    return (
        await storage.generate_presigned_download_url(
            object_key=version.signed_artifact_object_key,
            file_name=file_name,
            content_type="application/pdf",
        ),
        file_name,
    )


async def create_aws_cut(
    session: AsyncSession, context: AuthContext, data: AwsConsumptionCutCreate
) -> AwsConsumptionCut:
    await _customer(session, context, data.party_id)
    entity = AwsConsumptionCut(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity


async def create_billing_proposal(
    session: AsyncSession, context: AuthContext, data: BillingProposalCreate
) -> BillingProposal:
    await _customer(session, context, data.party_id)
    if data.contract_version_id is None and not data.exception_reason:
        raise HTTPException(
            status_code=422, detail="A contract version or documented exception is required"
        )
    if data.contract_version_id is not None:
        version = await session.scalar(
            select(ContractVersion)
            .join(CommercialContract, ContractVersion.contract_id == CommercialContract.id)
            .where(
                ContractVersion.id == data.contract_version_id,
                ContractVersion.tenant_id == context.tenant_id,
                CommercialContract.party_id == data.party_id,
            )
        )
        if version is None:
            raise HTTPException(status_code=404, detail="Contract version not found")
    if data.aws_consumption_cut_id is not None:
        cut = await session.scalar(
            select(AwsConsumptionCut).where(
                AwsConsumptionCut.id == data.aws_consumption_cut_id,
                AwsConsumptionCut.tenant_id == context.tenant_id,
                AwsConsumptionCut.party_id == data.party_id,
                AwsConsumptionCut.status.in_(["RECONCILED", "REVIEWED"]),
            )
        )
        if cut is None:
            raise HTTPException(
                status_code=422, detail="A reconciled AWS consumption cut is required"
            )
    entity = BillingProposal(tenant_id=context.tenant_id, **data.model_dump(by_alias=False))
    session.add(entity)
    await session.flush()
    return entity
