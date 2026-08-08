"""Status bounded-context read models and projections.

Status projections turn registry, run history, active state, and todo read
models into agent/operator-visible observations. Quota and CLI callers consume
these projections; they do not reimplement status facts.
"""
