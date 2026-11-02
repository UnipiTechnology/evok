# The [OAD(...)] marks in docs/spec.md read the OpenAPI document from a URL. The sources are
# fetched by essentials-openapi (neoteroi.mkdocsoad) by an httpx client which does not follow
# redirects, but the assets of a GitHub release reply by a 302 redirect to release-assets...,
# whose empty body breaks the build ("NoneType has no attribute 'get'" of yaml.safe_load("")),
# until essentials-openapi follows redirects. The hook replaces the client until then.

import httpx
import openapidocs.utils.web


def on_config(config):
    openapidocs.utils.web.http_client = httpx.Client(
        verify=False, timeout=20, follow_redirects=True
    )
