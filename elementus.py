from typing import Dict, List, Optional
from enum import IntEnum
from pydantic import BaseModel, Field, HttpUrl
from aiohttp import ClientSession, ClientTimeout
import asyncio
from datetime import timedelta

class OFACSanctionStatus(IntEnum):
    """Enum representing OFAC sanction status"""
    NOT_SANCTIONED = 0
    SANCTIONED = 1

class AttributionData(BaseModel):
    """Data model for wallet attribution information"""
    beneficial_owner: Optional[str] = Field(
        None, 
        description='The ultimate beneficial owner of the wallet'
    )
    custodian: Optional[str] = Field(
        None, 
        description='The custodian service holding the assets, if applicable'
    )
    entity: Optional[str] = Field(
        None, 
        description='The entity name associated with this wallet'
    )
    is_ofac_sanctioned: Optional[OFACSanctionStatus] = Field(
        None,
        description='Flag indicating if the entity is OFAC sanctioned'
    )
    sdn_name: Optional[str] = Field(
        None, 
        description='The Specially Designated Nationals (SDN) name if sanctioned'
    )
    wallet_id: Optional[str] = Field(
        None, 
        description='The wallet address'
    )

class AddressAttributionsRequest(BaseModel):
    """Request model for address attributions"""
    addresses: List[str] = Field(
        ...,
        description='List of addresses to get attributions for',
        min_items=1,
        max_items=10000,  # Adding a reasonable limit
        example=['1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa']
    )

class AddressAttributionsResponse(BaseModel):
    """Response model for address attributions"""
    data: Dict[str, AttributionData] = Field(
        default_factory=dict,
        description='Map of addresses to their attribution data'
    )

class ElementusAPIError(Exception):
    """Custom exception for Elementus API errors"""
    def __init__(self, status_code: int, error_data: Dict) -> None:
        self.status_code = status_code
        self.error_data = error_data
        super().__init__(f"API Error {status_code}: {error_data.get('message', 'Unknown error')}")

class ElementusClient:
    """Client for interacting with the Elementus Attribution API"""
    
    def __init__(
        self, 
        api_key: str,
        base_url: str = "https://attribution-api.elementus.io",
        timeout: float = 10.0
    ) -> None:
        """
        Initialize the Elementus API client.

        Args:
            api_key: API key for authentication
            base_url: Base URL for the API
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = ClientTimeout(total=timeout)
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json"
        }
        self._session: Optional[ClientSession] = None

    async def _get_session(self) -> ClientSession:
        """Get or create an aiohttp ClientSession."""
        if self._session is None or self._session.closed:
            self._session = ClientSession(timeout=self.timeout)
        return self._session

    async def close(self) -> None:
        """Close the client session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        **kwargs
    ) -> Dict:
        """
        Make an HTTP request to the API.

        Args:
            method: HTTP method
            endpoint: API endpoint
            **kwargs: Additional arguments to pass to aiohttp

        Returns:
            Dict containing the response data

        Raises:
            ElementusAPIError: If the API returns an error response
        """
        url = f"{self.base_url}{endpoint}"
        session = await self._get_session()
        
        async with session.request(method, url, headers=self.headers, **kwargs) as response:
            if response.status >= 400:
                try:
                    error_data = await response.json()
                except ValueError:
                    error_data = {"message": await response.text()}
                raise ElementusAPIError(response.status, error_data)
                
            return await response.json()

    async def get_address_attributions(
        self, 
        addresses: List[str]
    ) -> AddressAttributionsResponse:
        """
        Get attribution data for a list of addresses.

        Args:
            addresses: List of blockchain addresses to get attributions for

        Returns:
            AddressAttributionsResponse containing attribution data for the requested addresses

        Raises:
            ElementusAPIError: If the API request fails
            ValidationError: If the input or output validation fails
        """
        request = AddressAttributionsRequest(addresses=addresses)
        
        response_data = await self._make_request(
            "POST",
            "/address-attributions",
            json=request.model_dump()
        )
        
        return AddressAttributionsResponse.model_validate(response_data)

    async def check_health(self) -> bool:
        """
        Check the health status of the API.

        Returns:
            True if the API is healthy, raises ElementusAPIError otherwise
        """
        await self._make_request("GET", "/health")
        return True