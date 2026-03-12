# src/tth/adapters/avatar/__init__.py
"""Avatar adapter implementations."""

from tth.adapters.avatar.stub import StubAvatarAdapter
from tth.adapters.avatar.mock_cloud import MockCloudAvatarAdapter
from tth.adapters.avatar.did_streaming import DIDStreamingAvatar
from tth.adapters.avatar.simli import SimliAvatarAdapter

__all__ = [
    "StubAvatarAdapter",
    "MockCloudAvatarAdapter",
    "DIDStreamingAvatar",
    "SimliAvatarAdapter",
]
