"""
Motor de determinación de medidas aduaneras en tiempo real.

Capas:
    geography.py   — validación territorial (UE vs. terceros, excepciones)
    taric_client.py— proveedores HTTP en tiempo real (Access2Markets / UK)
    cache.py       — caché diaria (TTL) de medidas
    parser.py      — medidas crudas TARIC → estructura por partida
    knowledge.py   — base regulatoria no arancelaria (CBAM, EUDR, dual uso…)
    interpreter.py — capa de interpretación LLM
    service.py     — orquestador
    router.py      — endpoint FastAPI
"""
