"""错误码守卫测试（migration-plan 8.5：编号唯一 + AI 异常 7001-7005 全覆盖）。"""

from app.domain.errors import BusinessException, ErrorCode


class TestErrorCodeIntegrity:
    def test_codes_are_unique(self) -> None:
        codes = [ec.code for ec in ErrorCode]
        assert len(codes) == len(set(codes)), "存在重复的错误码编号"

    def test_ai_subdivision_codes_present(self) -> None:
        # 7001-7005 AI 异常细分全覆盖（migration-plan 8.6）
        ai_codes = {
            ErrorCode.AI_SERVICE_UNAVAILABLE.code,
            ErrorCode.AI_SERVICE_TIMEOUT.code,
            ErrorCode.AI_SERVICE_ERROR.code,
            ErrorCode.AI_API_KEY_INVALID.code,
            ErrorCode.AI_RATE_LIMIT_EXCEEDED.code,
        }
        assert ai_codes == {7001, 7002, 7003, 7004, 7005}

    def test_every_code_has_nonempty_message(self) -> None:
        for ec in ErrorCode:
            assert ec.message, f"{ec.name} 缺少错误信息"

    def test_business_exception_defaults_to_code_message(self) -> None:
        exc = BusinessException(ErrorCode.AI_SERVICE_TIMEOUT)
        assert exc.error_code is ErrorCode.AI_SERVICE_TIMEOUT
        assert exc.message == ErrorCode.AI_SERVICE_TIMEOUT.message
