# Контракт выходных файлов

При успешной генерации создаются:

- `process.bpmn` — BPMN 2.0 + BPMN DI;
- `process.xml` — XML-копия;
- `process.svg` — вектор;
- `process.pdf` — векторный PDF;
- `process.png` — высокое разрешение;
- `process.jpg` — JPEG;
- `process.webp` — WebP;
- `process.tiff` — TIFF;
- `process.eps` — EPS, если найден Inkscape;
- `process.html` — просмотр в браузере;
- `process-model.json` — исходная модель;
- `brief-description.md` — краткое описание;
- `validation-report.txt` — проверка;
- `all-formats.zip` — полный архив.

Не создавай фиктивный EPS, если Inkscape отсутствует. Запиши это в report.
