from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.errors import BusinessException, ErrorCode
from app.application.resume.analysis import (
    ResumeAnalysisResult,
    ResumeAnalysisService,
    ScoreDetail,
    Suggestion,
)


def _make_result() -> ResumeAnalysisResult:
    return ResumeAnalysisResult(
        overallScore=88,
        scoreDetail=ScoreDetail(
            projectScore=35,
            skillMatchScore=18,
            contentScore=13,
            structureScore=12,
            expressionScore=10,
        ),
        summary="资深 Java 工程师，项目经验扎实",
        strengths=["高并发经验丰富", "分布式系统设计能力强"],
        suggestions=[
            Suggestion(category="项目", priority="高", issue="项目描述偏笼统", recommendation="补充量化指标"),
        ],
    )


def _make_service() -> tuple[ResumeAnalysisService, dict[str, MagicMock]]:
    llm_registry = MagicMock()
    llm_registry.get_chat_client = AsyncMock(return_value=MagicMock())
    invoker = MagicMock()
    invoker.invoke = AsyncMock(return_value=_make_result())
    service = ResumeAnalysisService(llm_registry=llm_registry, invoker=invoker)
    return service, {"llm_registry": llm_registry, "invoker": invoker}


def _mock_prompt(name: str) -> MagicMock:
    tpl = MagicMock()
    tpl.format = MagicMock(return_value=f"prompt-{name}")
    return tpl


class TestAnalyzeResumeSuccess:
    @patch("app.application.resume.analysis.load_prompt")
    async def test_returns_llm_result_with_scores(self, mock_load: MagicMock) -> None:
        service, deps = _make_service()
        mock_load.side_effect = [_mock_prompt("system"), _mock_prompt("user")]

        result = await service.analyze_resume("张三 Java 工程师 5年经验")

        assert isinstance(result, ResumeAnalysisResult)
        assert result.overallScore == 88
        assert result.scoreDetail.projectScore == 35
        assert result.scoreDetail.skillMatchScore == 18
        assert result.summary == "资深 Java 工程师，项目经验扎实"
        assert result.strengths == ["高并发经验丰富", "分布式系统设计能力强"]
        assert len(result.suggestions) == 1
        assert result.suggestions[0].category == "项目"

    @patch("app.application.resume.analysis.load_prompt")
    async def test_renders_user_prompt_with_resume_text(self, mock_load: MagicMock) -> None:
        service, deps = _make_service()
        user_tpl = MagicMock()
        user_tpl.format = MagicMock(return_value="rendered-user-prompt")
        system_tpl = MagicMock()
        system_tpl.format = MagicMock(return_value="rendered-system-prompt")
        mock_load.side_effect = [system_tpl, user_tpl]

        await service.analyze_resume("简历内容XYZ")

        user_tpl.format.assert_called_once_with(resumeText="简历内容XYZ")

    @patch("app.application.resume.analysis.load_prompt")
    async def test_passes_prompts_and_model_to_invoker(self, mock_load: MagicMock) -> None:
        service, deps = _make_service()
        mock_load.side_effect = [_mock_prompt("system"), _mock_prompt("user")]

        await service.analyze_resume("text")

        call_kwargs = deps["invoker"].invoke.call_args.kwargs
        assert call_kwargs["output_model"] is ResumeAnalysisResult
        assert call_kwargs["error_code"] == ErrorCode.RESUME_ANALYSIS_FAILED
        assert call_kwargs["system_prompt"] == "prompt-system"
        assert call_kwargs["user_prompt"] == "prompt-user"


class TestAnalyzeResumeDegradation:
    @patch("app.application.resume.analysis.load_prompt")
    async def test_returns_degraded_result_on_llm_failure(self, mock_load: MagicMock) -> None:
        service, deps = _make_service()
        mock_load.side_effect = [_mock_prompt("system"), _mock_prompt("user")]
        deps["invoker"].invoke.side_effect = BusinessException(ErrorCode.RESUME_ANALYSIS_FAILED, "LLM 超时")

        result = await service.analyze_resume("text")

        assert result.overallScore == 0
        assert result.scoreDetail.projectScore == 0
        assert result.summary != ""
        assert len(result.suggestions) == 1
        assert result.suggestions[0].category == "系统"
        assert result.suggestions[0].priority == "高"

    @patch("app.application.resume.analysis.load_prompt")
    async def test_degraded_result_has_zero_scores(self, mock_load: MagicMock) -> None:
        service, deps = _make_service()
        mock_load.side_effect = [_mock_prompt("system"), _mock_prompt("user")]
        deps["invoker"].invoke.side_effect = BusinessException(ErrorCode.AI_SERVICE_ERROR)

        result = await service.analyze_resume("text")

        assert result.overallScore == 0
        assert result.scoreDetail.contentScore == 0
        assert result.scoreDetail.structureScore == 0
        assert result.scoreDetail.skillMatchScore == 0
        assert result.scoreDetail.expressionScore == 0
        assert result.scoreDetail.projectScore == 0
        assert result.strengths == []

    @patch("app.application.resume.analysis.load_prompt")
    async def test_does_not_raise_on_failure(self, mock_load: MagicMock) -> None:
        service, deps = _make_service()
        mock_load.side_effect = [_mock_prompt("system"), _mock_prompt("user")]
        deps["invoker"].invoke.side_effect = BusinessException(ErrorCode.RESUME_ANALYSIS_FAILED)

        await service.analyze_resume("text")

    @patch("app.application.resume.analysis.load_prompt")
    async def test_non_llm_error_propagates(self, mock_load: MagicMock) -> None:
        service, _ = _make_service()
        mock_load.side_effect = FileNotFoundError("prompt template missing")

        with pytest.raises(FileNotFoundError):
            await service.analyze_resume("text")


class TestScoreDetailRanges:
    def test_score_fields_match_prompt_output_format(self) -> None:
        result = _make_result()
        assert (
            result.scoreDetail.projectScore
            + result.scoreDetail.skillMatchScore
            + result.scoreDetail.contentScore
            + result.scoreDetail.structureScore
            + result.scoreDetail.expressionScore
            == 88
        )
