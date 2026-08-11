"""Backtest con agencia (experimento). Vive FUERA de mova_fpl a proposito:

el paquete garantiza que su unica primitiva de red es un GET
(tests/test_readonly_http.py); el POST a OpenRouter del agente LLM
pertenece al experimento, no al motor.
"""
