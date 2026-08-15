"""
CoT (Cursor on Target) Message Builder

Builds XML messages for TAK protocol.
Simple, focused builders for common use cases.
"""

from datetime import datetime, timezone, timedelta
import time
from typing import Optional


class CoTBuilder:
    """Build CoT XML messages for TAK server"""

    @staticmethod
    def build_marker(
        lat: float,
        lon: float,
        callsign: str,
        message: Optional[str] = None,
        uid: Optional[str] = None,
        stale_minutes: int = 60
    ) -> str:
        """
        Build a simple marker/point CoT message.

        Args:
            lat: Latitude (-90 to 90)
            lon: Longitude (-180 to 180)
            callsign: Display name for the marker
            message: Optional message/remarks to attach
            uid: Unique ID (auto-generated if not provided)
            stale_minutes: How long until marker expires (default 60 minutes)

        Returns:
            CoT XML string ready to send
        """
        if uid is None:
            uid = f"soldieriq-marker-{int(time.time())}"

        now = datetime.now(timezone.utc)
        stale = now + timedelta(minutes=stale_minutes)

        # CoT type for friendly marker: a-f-G-E-S
        # a = atom (individual point)
        # f = friendly
        # G = ground
        # E = equipment
        # S = sensor
        cot_type = "a-f-G-E-S"

        remarks = f"<remarks>{message}</remarks>" if message else ""

        cot_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="{uid}" type="{cot_type}" time="{now.isoformat()}" start="{now.isoformat()}" stale="{stale.isoformat()}" how="h-e">
    <point lat="{lat}" lon="{lon}" hae="0" ce="10" le="10"/>
    <detail>
        <contact callsign="{callsign}"/>
        {remarks}
    </detail>
</event>'''
        return cot_xml

    @staticmethod
    def build_chat_message(
        sender_uid: str,
        sender_callsign: str,
        message: str,
        recipient_uid: Optional[str] = None,
        recipient_callsign: Optional[str] = None
    ) -> str:
        """
        Build a chat message CoT.

        Args:
            sender_uid: Unique ID of sender
            sender_callsign: Display name of sender
            message: Chat message text
            recipient_uid: Optional recipient UID (None for broadcast)
            recipient_callsign: Optional recipient callsign

        Returns:
            CoT XML string for chat message
        """
        now = datetime.now(timezone.utc)
        stale = now + timedelta(hours=1)

        # Chat message type
        cot_type = "b-t-f"  # bit-text-friendly

        # Build recipient tags if specified
        to_tag = ""
        if recipient_uid and recipient_callsign:
            to_tag = f'<__serverdestination destinations="{recipient_uid}"/>'
            to_tag += f'<marti><dest callsign="{recipient_callsign}"/></marti>'

        chat_uid = f"{sender_uid}-chat-{int(time.time())}"

        cot_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="{chat_uid}" type="{cot_type}" time="{now.isoformat()}" start="{now.isoformat()}" stale="{stale.isoformat()}" how="h-e">
    <point lat="0" lon="0" hae="0" ce="9999999" le="9999999"/>
    <detail>
        <__chat id="{chat_uid}" chatroom="All Chat Rooms" parent="RootContactGroup" senderCallsign="{sender_callsign}">
            <chatgrp uid0="{sender_uid}" uid1="All Chat Rooms" id="All Chat Rooms"/>
        </__chat>
        <link uid="{sender_uid}" relation="p-p" type="a-f-G-E-S"/>
        <remarks>{message}</remarks>
        {to_tag}
    </detail>
</event>'''
        return cot_xml

    @staticmethod
    def build_route(
        points: list[tuple[float, float]],
        route_name: str,
        uid: Optional[str] = None,
        color: str = "255"  # ARGB color (default: blue)
    ) -> list[str]:
        """
        Build route CoT messages (returns list of messages).

        Args:
            points: List of (lat, lon) tuples
            route_name: Display name for route
            uid: Base UID for route (auto-generated if not provided)
            color: ARGB color value

        Returns:
            List of CoT XML strings (one per waypoint)
        """
        if uid is None:
            uid = f"soldieriq-route-{int(time.time())}"

        messages = []
        now = datetime.now(timezone.utc)
        stale = now + timedelta(hours=2)

        for idx, (lat, lon) in enumerate(points):
            waypoint_uid = f"{uid}-wp{idx}"
            waypoint_name = f"{route_name} WP{idx+1}"

            # Route waypoint type
            cot_type = "b-m-p-w"  # bit-marker-point-waypoint

            cot_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<event version="2.0" uid="{waypoint_uid}" type="{cot_type}" time="{now.isoformat()}" start="{now.isoformat()}" stale="{stale.isoformat()}" how="h-e">
    <point lat="{lat}" lon="{lon}" hae="0" ce="10" le="10"/>
    <detail>
        <contact callsign="{waypoint_name}"/>
        <link uid="{uid}" relation="p-p" type="b-m-p-w"/>
        <color value="{color}"/>
    </detail>
</event>'''
            messages.append(cot_xml)

        return messages
