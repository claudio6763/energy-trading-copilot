"""Orquestracao do motor de curva — nao e o motor, chama o motor vendorizado.

`snapshot.py`  modelo de dados do snapshot congelado (parte cara do pipeline).
`avaliar.py`   a parte barata: premio -> sinal -> risco por vertice -> book.

Nada aqui reimplementa `motor_curva/`. Numero que motor_curva ja calcula nunca
e recalculado por conta propria neste pacote.
"""
