import os

import pytest
from langchain_core.prompts import PromptTemplate

from app.infrastructure.ai.prompt_loader import load_prompt


class TestLoadPromptAllTemplates:
    @pytest.mark.parametrize(
        "name",
        [
            "interview-evaluation-summary-system",
            "interview-evaluation-summary-user",
            "interview-evaluation-system",
            "interview-evaluation-user",
            "interview-question-resume-system",
            "interview-question-resume-user",
            "interview-question-skill-system",
            "interview-question-skill-user",
            "jd-parse-system",
            "knowledgebase-query-rewrite",
            "knowledgebase-query-system",
            "knowledgebase-query-user",
            "resume-analysis-system",
            "resume-analysis-user",
        ],
    )
    async def test_loads_all_14_templates(self, name: str) -> None:
        template = await load_prompt(name)
        assert isinstance(template, PromptTemplate)

    def test_total_template_count_is_15(self) -> None:
        prompts_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "app", "prompts")
        st_files = [f for f in os.listdir(prompts_dir) if f.endswith(".st")]
        assert len(st_files) == 15


class TestLoadPromptInputVariables:
    async def test_resume_analysis_user_has_resume_text(self) -> None:
        template = await load_prompt("resume-analysis-user")
        assert "resumeText" in template.input_variables

    async def test_knowledgebase_query_rewrite_has_question_and_history(self) -> None:
        template = await load_prompt("knowledgebase-query-rewrite")
        assert "question" in template.input_variables
        assert "history" in template.input_variables

    async def test_system_prompts_have_no_variables(self) -> None:
        template = await load_prompt("resume-analysis-system")
        assert template.input_variables == []

    async def test_interview_evaluation_user_has_resume_text(self) -> None:
        template = await load_prompt("interview-evaluation-user")
        assert "resumeText" in template.input_variables
        assert "qaRecords" in template.input_variables

    async def test_jd_parse_system_has_reference_file_list(self) -> None:
        template = await load_prompt("jd-parse-system")
        assert "referenceFileList" in template.input_variables


class TestLoadPromptFormat:
    async def test_format_with_variables(self) -> None:
        template = await load_prompt("resume-analysis-user")
        result = template.format(resumeText="张三的简历内容")
        assert "张三的简历内容" in result

    async def test_format_system_prompt_no_vars(self) -> None:
        template = await load_prompt("interview-evaluation-system")
        result = template.format()
        assert len(result) > 0

    async def test_format_knowledgebase_query_user(self) -> None:
        template = await load_prompt("knowledgebase-query-user")
        result = template.format(context="知识库上下文", question="什么是Spring Boot?")
        assert "知识库上下文" in result
        assert "什么是Spring Boot?" in result


class TestLoadPromptCaching:
    async def test_same_instance_returned(self) -> None:
        t1 = await load_prompt("resume-analysis-system")
        t2 = await load_prompt("resume-analysis-system")
        assert t1 is t2


class TestLoadPromptNotFound:
    async def test_nonexistent_template_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            await load_prompt("nonexistent-prompt")
