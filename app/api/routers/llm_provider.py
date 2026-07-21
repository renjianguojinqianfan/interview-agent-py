from fastapi import APIRouter, Depends, Request

from app.api.deps import get_llm_provider_service
from app.api.rate_limit import global_key, limiter
from app.api.responses import Result
from app.application.llm_provider.schemas import (
    AsrConfigDTO,
    AsrConfigRequest,
    CreateProviderRequest,
    DefaultProviderDTO,
    ProviderDTO,
    ProviderTestResult,
    TtsConfigDTO,
    TtsConfigRequest,
    UpdateProviderRequest,
)
from app.application.llm_provider.service import LlmProviderService

router = APIRouter(prefix="/api/llm-provider", tags=["LLM供应商管理"])


@router.post("", response_model=Result[None])
@limiter.limit("5/second", key_func=global_key)
async def create_provider(
    request: Request,  # noqa: ARG001
    body: CreateProviderRequest,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[None]:
    await service.create_provider(body)
    return Result.success()


@router.post("/reload", response_model=Result[None])
@limiter.limit("5/second", key_func=global_key)
async def reload_providers(
    request: Request,  # noqa: ARG001
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[None]:
    await service.reload_providers()
    return Result.success()


@router.get("/list", response_model=Result[list[ProviderDTO]])
@limiter.limit("30/second", key_func=global_key)
async def list_providers(
    request: Request,  # noqa: ARG001
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[list[ProviderDTO]]:
    return Result.success(data=await service.list_providers())


@router.get("/default-provider", response_model=Result[DefaultProviderDTO])
@limiter.limit("30/second", key_func=global_key)
async def get_default_provider(
    request: Request,  # noqa: ARG001
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[DefaultProviderDTO]:
    return Result.success(data=await service.get_default_provider())


@router.put("/default-provider", response_model=Result[None])
@limiter.limit("5/second", key_func=global_key)
async def update_default_provider(
    request: Request,  # noqa: ARG001
    body: DefaultProviderDTO,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[None]:
    await service.update_default_provider(body)
    return Result.success()


@router.put("/default-embedding-provider", response_model=Result[None])
@limiter.limit("5/second", key_func=global_key)
async def update_default_embedding_provider(
    request: Request,  # noqa: ARG001
    body: DefaultProviderDTO,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[None]:
    await service.update_default_embedding_provider(body)
    return Result.success()


@router.get("/voice/asr", response_model=Result[AsrConfigDTO])
@limiter.limit("30/second", key_func=global_key)
async def get_asr_config(
    request: Request,  # noqa: ARG001
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[AsrConfigDTO]:
    return Result.success(data=await service.get_asr_config())


@router.put("/voice/asr", response_model=Result[None])
@limiter.limit("5/second", key_func=global_key)
async def update_asr_config(
    request: Request,  # noqa: ARG001
    body: AsrConfigRequest,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[None]:
    await service.update_asr_config(body)
    return Result.success()


@router.get("/voice/tts", response_model=Result[TtsConfigDTO])
@limiter.limit("30/second", key_func=global_key)
async def get_tts_config(
    request: Request,  # noqa: ARG001
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[TtsConfigDTO]:
    return Result.success(data=await service.get_tts_config())


@router.put("/voice/tts", response_model=Result[None])
@limiter.limit("5/second", key_func=global_key)
async def update_tts_config(
    request: Request,  # noqa: ARG001
    body: TtsConfigRequest,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[None]:
    await service.update_tts_config(body)
    return Result.success()


@router.post("/voice/asr/test", response_model=Result[ProviderTestResult])
@limiter.limit("10/second", key_func=global_key)
async def test_asr_config(
    request: Request,  # noqa: ARG001
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[ProviderTestResult]:
    return Result.success(data=await service.test_asr_config())


@router.post("/voice/tts/test", response_model=Result[ProviderTestResult])
@limiter.limit("10/second", key_func=global_key)
async def test_tts_config(
    request: Request,  # noqa: ARG001
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[ProviderTestResult]:
    return Result.success(data=await service.test_tts_config())


@router.get("/{provider_id}", response_model=Result[ProviderDTO])
@limiter.limit("30/second", key_func=global_key)
async def get_provider(
    request: Request,  # noqa: ARG001
    provider_id: int,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[ProviderDTO]:
    return Result.success(data=await service.get_provider(provider_id))


@router.put("/{provider_id}", response_model=Result[None])
@limiter.limit("5/second", key_func=global_key)
async def update_provider(
    request: Request,  # noqa: ARG001
    provider_id: int,
    body: UpdateProviderRequest,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[None]:
    await service.update_provider(provider_id, body)
    return Result.success()


@router.delete("/{provider_id}", response_model=Result[None])
@limiter.limit("5/second", key_func=global_key)
async def delete_provider(
    request: Request,  # noqa: ARG001
    provider_id: int,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[None]:
    await service.delete_provider(provider_id)
    return Result.success()


@router.post("/{provider_id}/test", response_model=Result[ProviderTestResult])
@limiter.limit("10/second", key_func=global_key)
async def test_provider(
    request: Request,  # noqa: ARG001
    provider_id: int,
    service: LlmProviderService = Depends(get_llm_provider_service),
) -> Result[ProviderTestResult]:
    return Result.success(data=await service.test_provider(provider_id))
