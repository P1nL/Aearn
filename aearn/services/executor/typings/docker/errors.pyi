"""Exception classes exposed by docker==7.1.0 at the executor boundary."""


class DockerException(Exception): ...


class APIError(DockerException): ...


class NotFound(DockerException): ...
