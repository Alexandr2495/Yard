# -*- coding: utf-8 -*-
"""
Пакет для работы с согласием на обработку персональных данных
"""

from .consent_manager import ConsentManager, CONSENT_TEXTS
from .handlers import consent_router, ConsentMiddleware

__all__ = ['ConsentManager', 'CONSENT_TEXTS', 'consent_router', 'ConsentMiddleware']


