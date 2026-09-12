# Test Report

Навык протестирован на примере `examples/simple-approval.json`.

Результат сборки: **PASS**.

Проверено:
- BPMN/XML создаются;
- SVG/PDF/PNG/JPG/WEBP/TIFF создаются;
- EPS создается при наличии Inkscape;
- HTML-просмотр создается;
- JSON-модель и краткое описание сохраняются;
- ZIP собирается;
- битые ссылки: 0;
- диагональные Sequence Flow: 0;
- off-boundary endpoints: 0;
- non-perpendicular target entries: 0;
- Sequence Flow across Pools: 0;
- Message Flow inside same Pool: 0;
- Tasks crossing Lane boundaries: 0;
- flows through unrelated nodes: 0;
- overlapping collinear Sequence Flow segments: 0.

Официальная OMG BPMN XSD validation не заявляется, пока официальная XSD не подключена отдельно.
