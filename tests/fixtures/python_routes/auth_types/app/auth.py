from typing import Annotated

from fastapi import Depends


class AuthSubject:
    pass


def check_portal_role():
    return None


PortalWrite = Annotated[AuthSubject, Depends(check_portal_role)]
