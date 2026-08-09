"""Outbound clients — the only modules allowed to know about foreign APIs.

`ml_client` is the single seam between gateway/worker and the standalone ML
Service (02_Architecture/04_ML_Service.md §3): no route, task, or service may
learn the ML Service URL or payload shape from anywhere else.
"""
