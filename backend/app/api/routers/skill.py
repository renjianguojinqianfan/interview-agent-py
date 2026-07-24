"""技能管理 API 路由：列表、详情、JD 解析。"""

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_skill_service
from app.api.rate_limit import limiter
from app.api.responses import Result
from app.application.skill.schemas import CategoryDTO, ParseJdRequest, SkillDTO
from app.application.skill.service import SkillService

router = APIRouter(prefix="/api/interview/skills", tags=["技能管理"])


@router.get("", response_model=Result[list[SkillDTO]])
async def list_skills(
    service: SkillService = Depends(get_skill_service),
) -> Result[list[SkillDTO]]:
    data = await service.list_skills()
    return Result.success(data=data)


@router.get("/{skill_id}", response_model=Result[SkillDTO])
async def get_skill(
    skill_id: str,
    service: SkillService = Depends(get_skill_service),
) -> Result[SkillDTO]:
    data = await service.get_skill(skill_id)
    return Result.success(data=data)


@router.post("/parse-jd", response_model=Result[list[CategoryDTO]])
@limiter.limit("5/second")
async def parse_jd(
    request: Request,  # noqa: ARG001  slowapi 限流必需
    body: ParseJdRequest,
    service: SkillService = Depends(get_skill_service),
) -> Result[list[CategoryDTO]]:
    data = await service.parse_jd(body.jd_text)
    return Result.success(data=data)
