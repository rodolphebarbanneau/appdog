import datetime
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import yaml
from httpx import Response

from appdog._internal.specs import AppSpec, EndpointInfo


class TestEndpointInfo:
    """Tests for the EndpointInfo dataclass."""

    def test_init(self) -> None:
        """Test initialization of EndpointInfo."""
        endpoint = EndpointInfo(
            name='get_users',
            method='get',
            path='/users',
            tags=['users'],
            operation_id='getUsers',
            summary='Get users',
            description='Get all users',
            parameters=[{'name': 'limit', 'in': 'query', 'schema': {'type': 'integer'}}],
            request_body=None,
            responses={'200': {'description': 'OK'}},
        )

        assert endpoint.name == 'get_users'
        assert endpoint.method == 'get'
        assert endpoint.path == '/users'
        assert endpoint.tags == ['users']
        assert endpoint.operation_id == 'getUsers'
        assert endpoint.summary == 'Get users'
        assert endpoint.description == 'Get all users'
        assert endpoint.parameters == [
            {'name': 'limit', 'in': 'query', 'schema': {'type': 'integer'}}
        ]
        assert endpoint.request_body is None
        assert endpoint.responses == {'200': {'description': 'OK'}}


class TestAppSpec:
    """Tests for the AppSpec class."""

    @pytest.fixture
    def sample_data(self) -> dict[str, Any]:
        """Fixture providing sample OpenAPI data."""
        return {
            'openapi': '3.0.0',
            'info': {'title': 'Test API', 'version': '1.0.0'},
            'paths': {
                '/test': {
                    'get': {
                        'operationId': 'getTest',
                        'summary': 'Test endpoint',
                        'responses': {'200': {'description': 'Success'}},
                    }
                }
            },
        }

    @pytest.fixture
    def sample_spec(self, sample_data: dict[str, Any]) -> AppSpec:
        """Fixture providing a sample AppSpec."""
        return AppSpec(
            uri='http://example.com/openapi.json',
            data=sample_data,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            hash='sample_hash',
        )

    @pytest.fixture
    def fixture_path(self) -> Path:
        """Fixture providing path to test fixtures."""
        return Path(__file__).parent / 'fixtures'

    def test_init(self, sample_data: dict[str, Any]) -> None:
        """Test initialization of AppSpec."""
        timestamp = datetime.datetime.now(datetime.timezone.utc)
        spec = AppSpec(
            uri='http://example.com/openapi.json',
            data=sample_data,
            timestamp=timestamp,
            hash='sample_hash',
        )

        assert spec.uri == 'http://example.com/openapi.json'
        assert spec.data == sample_data
        assert spec.timestamp == timestamp
        assert spec.hash == 'sample_hash'

    @pytest.mark.asyncio
    async def test_fetch_local_json(self, fixture_path: Path, tmp_path: Path) -> None:
        """Test fetching from a local JSON file."""
        # Create a sample JSON file
        json_file = tmp_path / 'spec.json'
        with open(json_file, 'w') as f:
            json.dump({'openapi': '3.0.0', 'info': {'title': 'Test API', 'version': '1.0.0'}}, f)

        # Fetch the specification
        spec = await AppSpec.fetch(str(json_file))

        assert spec.uri == str(json_file)
        assert spec.data == {'openapi': '3.0.0', 'info': {'title': 'Test API', 'version': '1.0.0'}}
        assert isinstance(spec.timestamp, datetime.datetime)
        assert isinstance(spec.hash, str)

    @pytest.mark.asyncio
    async def test_fetch_local_yaml(self, fixture_path: Path) -> None:
        """Test fetching from a local YAML file."""
        yaml_file = fixture_path / 'spec_basic.yaml'

        # Fetch the specification
        with patch('appdog._internal.specs.json.load') as mock_json_load:
            # Mock json.load to load YAML file since we're testing with YAML but code expects JSON
            with open(yaml_file) as f:
                yaml_content = yaml.safe_load(f)
            mock_json_load.return_value = yaml_content

            spec = await AppSpec.fetch(str(yaml_file))

        assert spec.uri == str(yaml_file)
        assert spec.data['openapi'] == '3.0.0'
        assert spec.data['info']['title'] == 'Test API'
        assert isinstance(spec.timestamp, datetime.datetime)
        assert isinstance(spec.hash, str)

    @pytest.mark.asyncio
    async def test_fetch_local_invalid(self, tmp_path: Path) -> None:
        """Test fetching from an invalid local file."""
        # Create an invalid JSON file
        invalid_file = tmp_path / 'invalid.json'
        with open(invalid_file, 'w') as f:
            f.write('invalid json')

        # Fetch the specification with error
        with pytest.raises(ValueError, match='Failed to parse local specification'):
            await AppSpec.fetch(str(invalid_file))

    @pytest.mark.asyncio
    async def test_fetch_http(self) -> None:
        """Test fetching from an HTTP URL."""
        sample_data = {
            'openapi': '3.0.0',
            'info': {'title': 'Test API', 'version': '1.0.0'},
        }

        # Mock the HTTP response
        mock_response = MagicMock(spec=Response)
        mock_response.json.return_value = sample_data
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response

        with patch('httpx.AsyncClient', return_value=mock_client):
            spec = await AppSpec.fetch('http://example.com/openapi.json')

        assert spec.uri == 'http://example.com/openapi.json'
        assert spec.data == sample_data
        assert isinstance(spec.timestamp, datetime.datetime)
        assert isinstance(spec.hash, str)

    @pytest.mark.asyncio
    async def test_fetch_http_error(self) -> None:
        """Test fetching from an HTTP URL with error."""
        # Mock the HTTP error
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.side_effect = httpx.HTTPError('HTTP Error')

        with patch('httpx.AsyncClient', return_value=mock_client):
            with pytest.raises(ValueError, match='Failed to load specification'):
                await AppSpec.fetch('http://example.com/openapi.json')

    @pytest.mark.asyncio
    async def test_fetch_invalid_uri(self) -> None:
        """Test fetching from an invalid URI."""
        with pytest.raises(ValueError, match='Failed to load specification from'):
            await AppSpec.fetch('https://example.com/openapi.json')

    def test_lookup_no_filters(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints without filters."""
        # Add a path to the spec
        sample_spec.data['paths'] = {
            '/users': {
                'get': {
                    'operationId': 'getUsers',
                    'tags': ['users'],
                    'summary': 'Get users',
                    'parameters': [{'name': 'limit', 'in': 'query'}],
                    'responses': {'200': {'description': 'OK'}},
                }
            }
        }

        endpoints = sample_spec.lookup()

        assert len(endpoints) == 1
        endpoint = endpoints[0]
        assert endpoint.name == 'get_users'
        assert endpoint.method == 'get'
        assert endpoint.path == '/users'
        assert endpoint.tags == ['users']
        assert endpoint.operation_id == 'getUsers'
        assert endpoint.summary == 'Get users'

    def test_lookup_with_pattern(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints with pattern filters."""
        # Add multiple paths to the spec
        sample_spec.data['paths'] = {
            '/users': {
                'get': {
                    'operationId': 'getUsers',
                    'tags': ['users'],
                    'summary': 'Get users',
                }
            },
            '/pets': {
                'get': {
                    'operationId': 'getPets',
                    'tags': ['pets'],
                    'summary': 'Get pets',
                }
            },
        }

        # Look up with path pattern
        endpoints = sample_spec.lookup(filters={'path': r'/users'})

        assert len(endpoints) == 1
        assert endpoints[0].path == '/users'
        assert endpoints[0].name == 'get_users'

        # Test with no matches
        endpoints = sample_spec.lookup(filters={'path': r'/nonexistent'})
        assert len(endpoints) == 0

    def test_lookup_with_method_filters(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints with method filters."""
        # Add multiple methods to the spec
        sample_spec.data['paths'] = {
            '/users': {
                'get': {
                    'operationId': 'getUsers',
                    'tags': ['users'],
                    'summary': 'Get users',
                },
                'post': {
                    'operationId': 'createUser',
                    'tags': ['users'],
                    'summary': 'Create user',
                },
            }
        }

        # Test include_methods
        endpoints = sample_spec.lookup(include_methods=['get'])
        assert len(endpoints) == 1
        assert endpoints[0].method == 'get'
        assert endpoints[0].name == 'get_users'

        # Test exclude_methods
        endpoints = sample_spec.lookup(exclude_methods=['get'])
        assert len(endpoints) == 1
        assert endpoints[0].method == 'post'
        assert endpoints[0].name == 'post_users'

        # Test with LookupConfig
        lookup_config = {'include_methods': ['get']}
        endpoints = sample_spec.lookup(**lookup_config)  # type: ignore
        assert len(endpoints) == 1
        assert endpoints[0].method == 'get'
        assert endpoints[0].name == 'get_users'

    def test_lookup_with_tag_filters(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints with tag filters."""
        # Add multiple tags to the spec
        sample_spec.data['paths'] = {
            '/users': {
                'get': {
                    'operationId': 'getUsers',
                    'tags': ['users', 'public'],
                },
                'post': {
                    'operationId': 'createUser',
                    'tags': ['users', 'admin'],
                },
            }
        }

        # Look up with tag include filter
        endpoints = sample_spec.lookup(include_tags=['public'])
        assert len(endpoints) == 1
        assert 'public' in endpoints[0].tags
        assert endpoints[0].name == 'get_users'

        # Look up with tag exclude filter
        endpoints = sample_spec.lookup(exclude_tags=['admin'])
        assert len(endpoints) == 1
        assert 'admin' not in endpoints[0].tags
        assert endpoints[0].name == 'get_users'

    def test_lookup_with_petstore_spec(self, fixture_path: Path) -> None:
        """Test looking up endpoints with petstore spec."""
        # Load petstore spec
        import yaml

        with open(fixture_path / 'spec_petstore.yaml') as f:
            data = yaml.safe_load(f)

        # Create spec
        spec = AppSpec(
            uri='http://petstore.example.com',
            data=data,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            hash='petstore_hash',
        )

        # Look up endpoints
        endpoints = spec.lookup()

        # Verify endpoints
        assert len(endpoints) == 3
        endpoint_names = [e.name for e in endpoints]
        assert 'get_pets' in endpoint_names
        assert 'post_pets' in endpoint_names
        assert 'get_pets_by_pet_id' in endpoint_names

    def test_lookup_with_xquik_spec_filters_social_and_compose_tags(
        self, fixture_path: Path
    ) -> None:
        """Test tag and method filters against an API-key protected social API."""
        with open(fixture_path / 'spec_xquik.yaml') as f:
            data = yaml.safe_load(f)

        spec = AppSpec(
            uri='https://xquik.com/openapi.json',
            data=data,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
            hash='xquik_hash',
        )

        social_endpoints = spec.lookup(include_tags=['x'])
        compose_endpoints = spec.lookup(include_methods=['post'], include_tags=['compose'])

        assert len(social_endpoints) == 1
        assert social_endpoints[0].name == 'get_api_v1_x_tweets_search'
        assert social_endpoints[0].parameters[0]['name'] == 'q'
        assert social_endpoints[0].responses['401']['description'] == 'Authentication required'
        assert len(compose_endpoints) == 1
        assert compose_endpoints[0].name == 'post_api_v1_compose'
        assert compose_endpoints[0].request_body is not None

    def test_lookup_skip_non_operations(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints skips non-HTTP methods."""
        # Add parameters and other fields to path
        sample_spec.data['paths'] = {
            '/users': {
                'get': {
                    'operationId': 'getUsers',
                    'tags': ['users'],
                },
                'parameters': [{'name': 'limit', 'in': 'query'}],
            }
        }

        endpoints = sample_spec.lookup()
        assert len(endpoints) == 1
        assert endpoints[0].name == 'get_users'

    def test_lookup_skip_empty_operations(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints skips empty operations."""
        # Add empty operation
        sample_spec.data['paths'] = {
            '/users': {
                'get': {
                    'operationId': 'getUsers',
                    'tags': ['users'],
                },
                'post': None,
            }
        }

        endpoints = sample_spec.lookup()
        assert len(endpoints) == 1
        assert endpoints[0].name == 'get_users'

    def test_lookup_duplicate_endpoint(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints with duplicate operation IDs."""
        # Add multiple operations with same ID
        sample_spec.data['paths'] = {
            '/users': {
                'get': {
                    'operationId': 'getUsers',
                },
            },
            '/users2': {
                'get': {
                    'operationId': 'getUsers',
                },
            },
        }

        # This should now assert to check we have both endpoints despite the duplicate IDs
        endpoints = sample_spec.lookup()
        assert len(endpoints) == 2
        names = [e.name for e in endpoints]
        assert 'get_users' in names
        assert 'get_users2' in names

    def test_lookup_with_path_parameters(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints with path parameters."""
        # Add paths with parameters
        sample_spec.data['paths'] = {
            '/users/{userId}': {
                'get': {
                    'operationId': 'getUserById',
                    'parameters': [{'name': 'userId', 'in': 'path', 'required': True}],
                },
            },
            '/users/{userId}/posts/{postId}': {
                'get': {
                    'operationId': 'getUserPost',
                    'parameters': [
                        {'name': 'userId', 'in': 'path', 'required': True},
                        {'name': 'postId', 'in': 'path', 'required': True},
                    ],
                },
            },
        }

        endpoints = sample_spec.lookup()
        assert len(endpoints) == 2
        names = [e.name for e in endpoints]
        assert 'get_users_by_user_id' in names
        assert 'get_users_posts_by_user_id_and_post_id' in names

    def test_lookup_with_kwargs_regex(self, sample_spec: AppSpec) -> None:
        """Test looking up endpoints with regex pattern in kwargs."""
        # Add multiple paths to the spec
        sample_spec.data['paths'] = {
            '/users': {
                'get': {
                    'operationId': 'getUsers',
                    'tags': ['users'],
                    'summary': 'Get all users',
                }
            },
            '/users/search': {
                'get': {
                    'operationId': 'searchUsers',
                    'tags': ['users'],
                    'summary': 'Search users',
                }
            },
            '/pets': {
                'get': {
                    'operationId': 'getPets',
                    'tags': ['pets'],
                    'summary': 'Get all pets',
                }
            },
        }

        # Look up with regex string in kwargs for path
        endpoints = sample_spec.lookup(filters={'path': r'/users.*'})
        assert len(endpoints) == 2
        paths = [e.path for e in endpoints]
        assert '/users' in paths
        assert '/users/search' in paths

        # Look up with regex string in kwargs for summary
        endpoints = sample_spec.lookup(filters={'summary': r'.*all.*'})
        assert len(endpoints) == 2
        summaries = [e.summary for e in endpoints]
        assert 'Get all users' in summaries
        assert 'Get all pets' in summaries

        # Look up with multiple filters
        endpoints = sample_spec.lookup(filters={'path': r'/users.*', 'summary': r'Search.*'})
        assert len(endpoints) == 1
        assert endpoints[0].path == '/users/search'

        # Using compiled regex pattern
        import re

        path_pattern = re.compile(r'/users.*')
        endpoints = sample_spec.lookup(filters={'path': path_pattern})
        assert len(endpoints) == 2

    def test_equality(self, sample_data: dict[str, Any]) -> None:
        """Test equality comparison between AppSpec instances."""
        timestamp = datetime.datetime.now(datetime.timezone.utc)
        spec1 = AppSpec(
            uri='http://example.com/openapi.json',
            data=sample_data,
            timestamp=timestamp,
            hash='hash1',
        )

        # Same URI and hash
        spec2 = AppSpec(
            uri='http://example.com/openapi.json',
            data=sample_data,
            timestamp=datetime.datetime.now(datetime.timezone.utc),  # Different timestamp
            hash='hash1',
        )

        # Same URI, different hash
        spec3 = AppSpec(
            uri='http://example.com/openapi.json',
            data=sample_data,
            timestamp=timestamp,
            hash='hash2',
        )

        # Different URI
        spec4 = AppSpec(
            uri='http://example.com/another.json',
            data=sample_data,
            timestamp=timestamp,
            hash='hash1',
        )

        # Test equality
        assert spec1 == spec2  # Same URI and hash
        assert spec1 != spec3  # Same URI, different hash
        assert spec1 != spec4  # Different URI
        assert spec1 != 'not_a_spec'  # Different type

        # Test inequality
        assert not (spec1 != spec2)  # Same URI and hash
