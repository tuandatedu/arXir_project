# Cách chạy M2 trên Windows

Mở terminal PowerShell trong VS Code, rồi chạy từng lệnh bên dưới. Lệnh `cd`
đưa terminal tới thư mục gốc của repo trên máy hiện tại:

```powershell
cd 'D:\CODE\Năm 3\IntroDS\arXir_project'
python --version
```

Nếu `python` không chạy, cài Python 3.10 trở lên hoặc thay `python` bằng `py`
trong các lệnh bên dưới. Cài thư viện một lần:

```powershell
python -m pip install -r src/requirements.txt pytest
```

Kiểm tra code trước khi chạy toàn bộ:

```powershell
python -m pytest tests/test_m2_hierarchy.py tests/test_m2_standardization.py -q
```

Đảm bảo `range_1_dev` nằm ngay trong repo và chứa `batch_00000.tar.gz`,
`batch_00000.json`, ... `batch_00099.tar.gz`, `batch_00099.json`. Folder `range_1`
là references Semantic Scholar cho các bước sau, không cần truyền vào M2.

Chạy toàn bộ 100 batch:

```powershell
python -m src.m2_parsing.run_m2 --batch-dir range_1_dev --workers 4 --resume --working-dir data/working --tables-dir data/tables
```

Lệnh xác minh checksum, giải nén và xử lý lần lượt các batch. `--workers 4`
chạy bốn batch song song; nếu máy chậm hoặc thiếu RAM, giảm thành `--workers 2`.
Lần chạy đầu có thể mất nhiều phút và cần đủ dung lượng đĩa. Nếu ngắt giữa chừng,
chạy lại đúng lệnh: `--resume` dùng lại batch đã hoàn thành của đúng phiên bản code.
Những batch từ phiên bản pipeline cũ sẽ được xử lý lại. Trong lúc đang chạy,
các bảng tổng và metrics cũ không phải là kết quả của phiên bản mới.

Sau khi chạy xong, kết quả nằm trong `data/tables`:

- `elements.jsonl`, `hierarchy.jsonl`, `bibtex.jsonl`: ba bảng M2.
- `metrics_m2.json`: thống kê và coverage từng bài/version.
- `batches/`: kết quả từng batch để có thể chạy tiếp khi bị ngắt.

Xem thống kê bằng:

```powershell
python -c "import json; m=json.load(open('data/tables/metrics_m2.json',encoding='utf-8')); print({k:m[k] for k in ('n_publications','n_versions_total','n_versions_parsed','n_versions_empty','n_versions_failed','n_elements_after_dedup','n_bib_after')})"
python -c "import json; m=json.load(open('data/tables/metrics_m2.json',encoding='utf-8')); print([(p['arxiv_id'],p['failed_versions']) for p in m['coverage'] if p['failed_versions']])"
```

`n_versions_empty` chỉ tính version có marker rỗng của M1. Version thiếu source
hoặc không tìm thấy `\documentclass` nằm trong `failed_versions`; lệnh trả mã
thoát 2 nếu còn version lỗi. Bộ `range_1_dev` ban đầu có 5 version thiếu source
vì thư viện `.bib` lớn hơn giới hạn của lần crawl cũ.
Thông báo `Missing include` báo file không tìm thấy hoặc include dùng macro;
cần xem source cụ thể, không tự hiểu là toàn bộ version hoàn chỉnh.

## Chạy bộ checkpoint đã phục hồi năm bài

Trên máy này, `data/range_1_repaired` là bản checkpoint riêng đã bổ sung source
cho 5 bài; `range_1_dev` ban đầu vẫn được giữ nguyên. Kết quả mới ghi tại
`data/tables_repaired`. Sau khi đã phục hồi, dùng bộ này khi chạy lại M2: bộ
`range_1_dev` cũ vẫn chứa trạng thái lỗi và không có source của 5 bài. Để chạy
tiếp hoặc chạy lại với bộ đã phục hồi:

```powershell
python -m src.m2_parsing.run_m2 --batch-dir data/range_1_repaired --workers 2 --resume --working-dir data/working --tables-dir data/tables_repaired
```

Xem metrics của bộ đã phục hồi:

```powershell
python -c "import json; m=json.load(open('data/tables_repaired/metrics_m2.json',encoding='utf-8')); print({k:m[k] for k in ('n_publications','n_versions_total','n_versions_parsed','n_versions_empty','n_versions_failed')})"
```

Thư mục `data/repair_sources` lưu archive gốc tải lại và source đã giải nén;
`data/range_1_repaired/repair_log.json` ghi các batch và ID được bổ sung. Những
thư mục dữ liệu này không đi theo code trên git. Nếu dùng máy khác hoặc Colab,
cần chép bộ `data/range_1_repaired` sang máy đó.

Notebook báo cáo: `src/m2_parsing/report_m2.ipynb`. Mở notebook trong VS Code,
chọn kernel Python đã cài thư viện và chạy từ thư mục gốc repo. Nếu có metrics
trong `data/tables_repaired`, notebook sẽ tự dùng kết quả đã phục hồi. Để nộp bài còn
cần benchmark một lượt mới trên Google Colab CPU và ghép báo cáo vào Jupyter Book
của nhóm. Thời gian của một lượt `--resume` chỉ đo phần chạy lại, không phải thời
gian xử lý đầy đủ 5.000 bài.

Lưu ý: các môi trường công thức nhiều dòng có đánh số/nhãn được giữ nguyên để
không làm sai đánh số; macro trích dẫn tự định nghĩa và source thiếu include cần
kiểm tra thủ công. Dữ liệu và kết quả trong `data/`, `range_1/`, `range_1_dev/`
được git bỏ qua và không đi theo code khi push.
