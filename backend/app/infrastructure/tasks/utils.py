_ERROR_MAX_LENGTH = 500


def truncate_error(error: str) -> str:
    if len(error) > _ERROR_MAX_LENGTH:
        return error[:_ERROR_MAX_LENGTH]
    return error
