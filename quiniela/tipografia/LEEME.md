# Tipografía

`oswald-recortada.woff2` es la fuente **Oswald** (Vernon Adams, Kalapi Gajjar,
Cyreal), bajo licencia SIL Open Font License 1.1 — el texto completo está en
`OFL.txt`, que la licencia exige conservar junto al archivo.

Está **recortada a propósito**: solo mayúsculas, números y algunos signos
(`0-9 A-Z ÁÉÍÓÚÑ . , : · % $ + - / ° ( )`). Por eso pesa 8 KB en vez de 40.

Se usa únicamente donde el texto ya va en mayúsculas o es numérico —marcadores,
posiciones, montos, encabezados— nunca en nombres de participantes, que llevan
minúsculas y caerían a la fuente del sistema a media palabra.

`render_html.py` la incrusta en el HTML como base64 al generar la página, así
que el sitio sigue sin pedirle un solo archivo a nadie.

Para regenerarla con otros caracteres, pídele a Google Fonts el subconjunto:

    https://fonts.googleapis.com/css2?family=Oswald:wght@500;700&text=<caracteres>
