"""
Class that is responsible for HTTP communications with a FHIR server
"""

import logging
import json
from collections import defaultdict
from pprint import pformat

import requests
import urllib.parse

from utils import requests_retry_session, check_service_status
from config import FHIR_VERSION

logging.getLogger(
    requests.packages.urllib3.__package__).setLevel(logging.WARNING)


class FhirApiClient(object):

    def __init__(self, base_url=None, auth=None, fhir_version=FHIR_VERSION,
                 status_endpoint=None):
        self.logger = logging.getLogger(type(self).__name__)
        self.base_url = base_url
        self.status_endpoint = status_endpoint
        self.auth = auth
        self.fhir_version = fhir_version
        self.session = requests_retry_session()

    def post_or_put_all(self, resource_dicts, endpoint=None, method='post'):
        """
        POST/PUT all FHIR resources to server. Send requests to endpoint if its
        provided, otherwise, get endpoint for each resource from its resource
        dict in resource_dicts

        Returns result dict containing successes and error results:

            {
                success: {
                    <resource filename>: <result dict>,
                    ...
                },
                errors: {
                    <resource filename>: <result dict>,
                    ...
                }
            }

        :param resource_dicts: list of resource content and metadata
        :type resource_dicts: list of dicts
        :param endpoint: Optional FHIR endpoint to use for all requests
        :type endpoint: str
        :param auth: basic auth parameters
        :type auth: requests.auth.HTTPBasicAuth object

        :returns: a tuple (success boolean, result dict) See send_request
        for details.
        """
        success = True
        results = defaultdict(dict)

        for rd in resource_dicts:
            filepath = rd['filepath']
            ep = rd.get('endpoint', endpoint)
            success_one, result = self.post_or_put(ep, rd, method=method)
            success = success_one & success

            if success_one:
                results['success'][filepath] = result
            else:
                results['errors'][filepath] = result

        return success, results

    def post_or_put(self, endpoint, resource_dict, method='post'):
        """
        POST OR PUT FHIR resource to server.

        Expected form of dict in resource_dicts:

        {
            'content': <dict>,
            'content_type': json,
            'resource_type': <FHIR resource type>,
            'filename': <resource source file name>
            'filepath': <path to resource source file>
        }

        :param endpoint: FHIR endpoint
        :type endpoint: str
        :param resource_dict: resource content and metadata
        :type resources: dict
        :param auth: basic auth parameters
        :type auth: requests.auth.HTTPBasicAuth object

        :returns: a tuple (success boolean, result dict) See send_request
        for details.
        """
        filename = resource_dict['filename']
        resource = resource_dict['content']
        resource_type = resource_dict['resource_type']

        self.logger.info(
            f'{method.upper()}ing FHIR {resource_type} from {filename}'
        )

        # Send post
        request_kwargs = {}
        request_kwargs['json'] = resource
        success, result = self.send_request(
            method, endpoint, **request_kwargs
        )

        if success:
            self.logger.info(
                f'✅ {method.upper()} {filename} to {endpoint} succeeded'
            )
        else:
            self.logger.info(
                f'❌ {method.upper()} {filename} to {endpoint} failed'
            )

        return success, result

    def delete_all(self, endpoint, **request_kwargs):
        """
        Delete FHIR resources at endpoint on FHIR server.

            - Send GET request to endpoint
            - For each valid result, send DELETE request

        :param endpoint: FHIR endpoint
        :type endpoint: str
        :param request_kwargs: optional request keyword args
        :type request_kwargs: key, value pairs
        :returns: a boolean indicating whether all items at endpoint were
        successfully deleted.
        """
        success = True

        self.logger.info('Begin deleting resources ...')

        # Fetch resources to delete
        if not request_kwargs.get('auth'):
            request_kwargs['auth'] = self.auth

        success, result = self.send_request(
            'get',
            endpoint,
            **request_kwargs
        )
        resp_content = result['response']
        request_url = result['request_url']
        self.logger.debug(
            f'Fetched {resp_content.get("total")} item(s) from {request_url}'
        )

        if not success:
            return False

        # Delete individual resources
        for entry in resp_content.get('entry', []):
            if entry['resource'].get('resourceType') == 'OperationOutcome':
                continue
            rs = entry['resource']
            url = f'{self.base_url}/{rs["resourceType"]}/{rs["id"]}'
            self.logger.debug(f'Deleting {url}')

            success_delete, result = self.send_request(
                'delete', url, auth=request_kwargs.get('auth')
            )
            success = success_delete & success

        return success

    def send_request(self, request_method_name, url, **request_kwargs):
        """
        Send request to the FHIR validation server. Return a tuple
        (success boolean, result dict).

        The success boolean represents whether the request was sucessful AND
        valid by the FHIR specification. The request is valid if there are no
        errors in the issues list of the response.

        The result dict looks like this:

            {
                'status_code': response.status_code,
                'response': response.json() or response.text
            }

        :param request_method_name: requests method name
        :type request_method_name: str
        :param url: FHIR url
        :type url: str
        :param request_kwargs: optional request keyword args
        :type request_kwargs: key, value pairs
        :returns: tuple of the form
        (success boolean, result dict)
        """
        success = False

        # Add request headers containing FHIR version information
        if self.auth:
            request_kwargs.update({'auth': self.auth})

        headers = request_kwargs.get('headers', {})
        if 'Content-Type' not in headers:
            headers.update(self._fhir_version_headers())
        request_kwargs['headers'] = headers

        # Send request
        request_method = getattr(self.session,
                                 request_method_name.lower())
        response = request_method(url, **request_kwargs)
        resp_content = self._response_content(response)

        # Determine success and log result
        request_method_name = request_method_name.upper()
        request_url = urllib.parse.unquote(response.url)

        success_status = {
            'GET': {200},
            'POST': {200, 201},
            'PUT': {200, 201},
            'DELETE': {204, 200},
        }

        if response.status_code in success_status.get(request_method_name, {}):
            errors = self._errors_from_response(resp_content)
            if not errors:
                success = True
                self.logger.debug(
                    f'{request_method_name} {request_url} succeeded. '
                    f'Response:\n{pformat(resp_content)}'
                )
            else:
                self.logger.debug(
                    f'{request_method_name} {request_url} failed. '
                    f'Caused by:\n{pformat(resp_content)}'
                )
        else:
            self.logger.debug(
                f'{request_method_name} {request_url} failed, '
                f'status {response.status_code}. '
                f'Caused by:\n{pformat(resp_content)}'
            )

        return success, {'status_code': response.status_code,
                         'request_url': request_url,
                         'response': resp_content}

    def check_service_status(self, exit_on_down=False, log_msg=None):
        """
        Check FHIR server status. Optionally exit if server is down and
        log a message to alert the user.
        """
        down = check_service_status(self.status_endpoint or self.base_url,
                                    auth=self.auth,
                                    headers=self._fhir_version_headers())
        if down:
            self.logger.error(log_msg)
            if exit_on_down:
                exit(1)

    def _fhir_version_headers(self):
        """
        Generate the FHIR Content-Type request header using the FHIR version
        of the server

        :returns: a dict containing request headers
        """
        if not self.fhir_version:
            return {}

        major_version = self.fhir_version.split('.')[0]

        return {
            'Content-Type':
            f'application/fhir+json; fhirVersion={major_version}.0'
        }

    def _response_content(self, response):
        """
        Try to parse response body as JSON, otherwise return the
        text version of body
        """
        try:
            resp_content = response.json()
        except json.decoder.JSONDecodeError:
            resp_content = response.text
        return resp_content

    def _errors_from_response(self, response_body):
        """
        Comb list of issues in FHIR response and return the ones marked error
        """
        response_body = response_body or {}
        return [issue for issue in response_body.get('issue', [])
                if issue['severity'] == 'error']
