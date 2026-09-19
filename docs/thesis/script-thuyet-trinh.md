# Script thuyết trình — Nhóm 5 · Truy vấn thông tin

> **Đề tài:** Nearby Location Recommendation — tìm kiếm & xếp hạng địa điểm theo vị trí
> **GVHD:** TS. GVC. Nguyễn Quốc Huy
> **Deck:** `Thuyết trình Nhóm 5.pptx` — 24 slide
> **Thời lượng mục tiêu:** ~16–18 phút trình bày + Q&A

## Phân công

| Phần | Slide | Người trình bày | Nội dung |
|------|-------|-----------------|----------|
| 1–2 | 1–8 | **Lê Thị Mai Len** | Giới thiệu, bài toán, kiến trúc, dữ liệu, demo |
| 3–4 | 9–17 | **Hoàng Châu Ngọc Phương** | Retrieval, Ranking, LTR, Ablation, Error Audit |
| 5–6 | 18–24 | **Tăng Ngọc Phụng** | Đánh giá, hiệu năng, triển khai, chỉ đường, kết luận |

> **Quy ước đọc script:** phần trong ngoặc kép là lời nói; phần in nghiêng trong `[...]` là chỉ dẫn thao tác (chuyển slide, chỉ vào biểu đồ), **không đọc**.

---

# PHẦN 1–2 · GIỚI THIỆU, KIẾN TRÚC & DỮ LIỆU
**Người trình bày: Lê Thị Mai Len — slide 1→8, ~5 phút**

## Slide 1 — Trang bìa
*(~20 giây)*

"Em xin kính chào thầy và các bạn. Nhóm em là nhóm 5, môn Truy vấn thông tin, dưới sự hướng dẫn của thầy Nguyễn Quốc Huy. Hôm nay nhóm em xin trình bày đề tài: hệ thống tìm kiếm và gợi ý địa điểm lân cận — Nearby Location Recommendation."

## Slide 2 — Thành viên nhóm
*(~15 giây)*

"Nhóm em gồm ba thành viên: Tăng Ngọc Phụng, Lê Thị Mai Len và Hoàng Châu Ngọc Phương. Em là Mai Len, sẽ trình bày phần đầu tiên."

## Slide 3 — Nội dung trình bày
*(~25 giây)*

"Bài trình bày gồm 6 phần: (1) Giới thiệu và bài toán; (2) Kiến trúc và dữ liệu; (3) Truy xuất và xếp hạng; (4) Ablation và phân tích lỗi; (5) Đánh giá và triển khai; (6) Chỉ đường và hạn chế. Em xin bắt đầu với phần 1 và 2."

## Slide 4 — Bài toán & mục tiêu
*(~60 giây)*

"Vấn đề đặt ra: người dùng muốn tìm một địa điểm GẦN mình, nhưng kết quả còn phải PHÙ HỢP với truy vấn.

Ví dụ khi gõ 'cà phê gần Bến Thành', hệ thống phải tách truy vấn làm hai phần: từ khóa là 'cà phê', còn vị trí là 'gần Bến Thành'. Nếu chỉ tìm theo khoảng cách thì có thể ra một quán ăn ngay cạnh nhưng không phải cà phê; ngược lại nếu chỉ tìm theo từ khóa thì lại ra quán cà phê cách 5 cây số.

Vì vậy nhóm đặt 4 mục tiêu: một là truy xuất đúng địa điểm liên quan; hai là xếp hạng kết quả theo mức phù hợp, khoảng cách và chất lượng; ba là cá nhân hóa theo ngữ cảnh như thời điểm, hành vi; và bốn là chỉ đường thật tới địa điểm bằng OSRM."

## Slide 5 — Kiến trúc tổng thể
*(~50 giây)*

*[Chỉ theo luồng mũi tên từ trên xuống]*

"Đây là kiến trúc tổng thể của hệ thống, gồm nhiều tầng. Người dùng nhập truy vấn và chia sẻ vị trí GPS ở tầng Client.

Yêu cầu đi qua Frontend — giao diện web có bản đồ và danh sách kết quả — rồi tới API Gateway lo việc định tuyến, gắn request-id và giới hạn tốc độ.

Trọng tâm nằm ở Backend, gồm hai khối: Search/Retrieval truy xuất ứng viên bằng nhiều kênh BM25, Geo và Vector; và Ranking xếp hạng lại bằng đa tín hiệu, hợp nhất bằng RRF. Cuối cùng hệ thống trả về danh sách POI và phần chỉ đường bằng OSRM."

## Slide 6 — Nguồn dữ liệu & xử lý dữ liệu
*(~60 giây)*

"Về dữ liệu, hệ thống dùng 3.010 địa điểm THẬT tại TP.HCM, trong đó 2.982 điểm lấy từ OpenStreetMap — một nguồn bản đồ mở, miễn phí. Mỗi POI được mô tả bằng nhiều thuộc tính: tên, tọa độ, danh mục, địa chỉ, giờ mở cửa, mức giá, tiện ích, tags, thương hiệu, mã không gian H3, vector 64 chiều và nguồn gốc dữ liệu.

Quy trình xử lý gồm 5 bước: một là thu thập từ OpenStreetMap bằng cách quét vùng bbox TP.HCM; hai là khử trùng lặp — những điểm cùng loại, tên giống nhau và cách nhau dưới 75 mét thì gộp làm một bản ghi canonical; ba là lập chỉ mục không gian H3 theo lưới lục giác ba mức 9, 8 và 7; bốn là sinh vector embedding 64 chiều bằng mô hình hashing-v2-64; và cuối cùng nạp toàn bộ vào OpenSearch để phục vụ tìm kiếm BM25, geo và vector."

## Slide 7 — Các nhóm dữ liệu & tín hiệu xếp hạng
*(~60 giây)*

"Từ dữ liệu đó, hệ thống chia thành hai nhóm. Bên trái là NHÓM DỮ LIỆU ĐỊA ĐIỂM — một chuỗi xử lý từ OpenStreetMap thành POI rồi lập chỉ mục Geo/H3.

Bên phải là NHÓM TÍN HIỆU XẾP HẠNG, gồm 9 tín hiệu, mỗi tín hiệu có một trọng số thể hiện mức độ quan trọng. Quan trọng nhất là Văn bản 0.26 — mức khớp từ khóa theo BM25, và Khoảng cách 0.24 — độ gần vị trí người dùng; đúng với bài toán 'gần và phù hợp'.

Các tín hiệu còn lại như Rating, độ mới, ngữ cảnh giờ mở cửa, gợi ý từ đồ thị tri thức, độ phổ biến, độ hot theo khu vực và tỉ lệ click bổ sung thêm. Chín trọng số này cộng lại bằng 1.

Cả hai nhóm cùng đổ vào bước Xếp hạng POI, nơi hệ thống hợp nhất bằng RRF và tổ hợp tuyến tính 9 tín hiệu. Cơ chế xếp hạng chi tiết sẽ do bạn Phương trình bày ở Phần 3."

## Slide 8 — Demo giao diện
*(~45 giây)*

"Cuối phần của em là demo giao diện thực tế. Đầu tiên, người dùng gõ từ khóa, ví dụ 'cà phê', rồi bấm Tìm. Thứ hai, có thể lọc theo danh mục như Ăn uống, Cà phê. Thứ ba, bấm vào một địa điểm để xem chi tiết POI ngay trên bản đồ. Và thứ tư, hệ thống hiển thị khoảng cách từ vị trí hiện tại tới địa điểm đó.

Đó là toàn bộ phần giới thiệu bài toán, kiến trúc và dữ liệu. Em xin mời bạn Phương trình bày tiếp phần truy xuất và xếp hạng."

---

# PHẦN 3–4 · TRUY XUẤT, XẾP HẠNG & PHÂN TÍCH LỖI
**Người trình bày: Hoàng Châu Ngọc Phương — slide 9→17, ~7 phút**

## Slide 9 — Tổng quan kiến trúc Search Pipeline
*(~60 giây)*

"Tiếp theo, em xin trình bày về quá trình xây dựng và cải tiến Search Pipeline của hệ thống.

Về tổng thể, pipeline được tách rời thành hai giai đoạn độc lập là Retrieval và Ranking. Đây là một lựa chọn kiến trúc có chủ đích: Retrieval ưu tiên tốc độ và độ phủ đa không gian, còn Ranking mới là nơi đánh giá chuyên sâu và tốn tài nguyên.

Ở giai đoạn Retrieval, hệ thống dùng bốn kênh tìm kiếm là BM25, Vector k-NN, Geo/H3 và Trending để thu thập một tập ứng viên có độ bao phủ cao. Các ứng viên được hợp nhất bằng RRF Fusion, lấy khoảng 300 ứng viên đầu, rồi hydrate — tức bổ sung dữ liệu chuẩn — từ PostGIS. PostGIS ở đây đóng vai trò 'mỏ neo' dữ liệu và là backup an toàn khi OpenSearch gặp sự cố.

Sau khi có candidate pool, hệ thống chuyển sang Ranking. Ban đầu nhóm dùng Linear Scoring với 9 tín hiệu, sau đó phát triển thêm Learning to Rank với LambdaMART.

Như vậy, quá trình cải tiến đi từ Retrieval → Fusion → Relevance Gate → Weighted Scoring → LTR, rồi được đánh giá qua các thí nghiệm và Error Analysis."

## Slide 10 — Retrieval đa kênh, RRF và Relevance Gate
*(~90 giây)*

"Ở tầng Retrieval, nhóm sử dụng bốn kênh chính. BM25 tìm theo mức độ khớp văn bản, có xử lý `_folded` nên chịu được lỗi gõ thiếu dấu tiếng Việt. Geo và H3 tìm ứng viên phù hợp về mặt không gian. Vector k-NN 64 chiều tìm ứng viên tương đồng về ngữ nghĩa. Và Trending bổ sung các địa điểm đang phổ biến, lấy từ Redis.

Mục tiêu của bước này là không phụ thuộc vào một nguồn duy nhất, mà quét đồng thời bốn không gian đặc trưng khác nhau để hạn chế bỏ sót địa điểm.

Về trọng số kênh: BM25 là 1.0, Vector k-NN 0.9, Trending 0.5, còn Geo và H3 được cân bằng sao cho tổng phần không gian bằng 0.6. Một kết quả thực nghiệm đáng chú ý là recall của H3 đạt 1.00 — nghĩa là H3 có thể thay thế truy vấn khoảng cách thuần mà không mất mát ứng viên nào.

Sau đó các danh sách được hợp nhất bằng RRF — Reciprocal Rank Fusion. RRF kết hợp theo THỨ HẠNG thay vì cộng trực tiếp score gốc, bởi vì BM25, Vector và các tín hiệu khác có thang điểm hoàn toàn khác nhau, cộng thẳng là không có ý nghĩa. Công thức dùng dạng weight chia cho k cộng rank, với k bằng 60.

Giá trị 60 được kế thừa từ nghiên cứu gốc của Cormack và cộng sự tại SIGIR 2009; trong nghiên cứu đó giá trị này được chọn bằng thực nghiệm để giảm ảnh hưởng quá lớn của vài thứ hạng đầu. Nhóm hiện dùng nguyên giá trị 60 làm mặc định và chưa thực nghiệm riêng để tối ưu lại k trên dữ liệu địa điểm của mình — đây là một hướng cải thiện trong tương lai.

Sau bước Fusion, nhóm bổ sung Relevance Gate. Relevance Gate KHÔNG làm tăng score BM25 hay Vector. Nó sắp xếp lại candidate, ưu tiên những ứng viên có ít nhất một tín hiệu BM25 hoặc Vector đứng trước những ứng viên chỉ có Geo, H3 hoặc Trending — bất kể điểm RRF của chúng. Đây chính là cơ chế bảo đảm ràng buộc 'phù hợp' mà bạn Len đã nêu ở phần đầu."

## Slide 11 — Linear Scoring & thực trạng 9 tín hiệu
*(~75 giây)*

*[Chỉ vào cột "Trạng thái thực tế" của bảng]*

"Sau khi có candidate pool, hệ thống chuyển sang bước Ranking. Ở phiên bản baseline, nhóm dùng tổ hợp tuyến tính 9 tín hiệu.

Bảng này là thực trạng thật, không phải thiết kế lý thuyết. Năm tín hiệu đang hoạt động tốt: text với trọng số 0.26, đã được sửa để textScore chính là bm25_score chuẩn hóa và phủ 82% ứng viên; distance 0.24 với hàm suy giảm mũ exp trừ d chia 1500; recency 0.12 đếm event thật theo ba mốc; graph 0.10 đã tích hợp vào API search từ Phase 3; và trending 0.08 tính theo ô H3 mức 8 với TTL 4 giờ.

Ba tín hiệu hiện đang vô hiệu: rating 0.12 thiếu dữ liệu đánh giá thực tế, popularity 0.08 thiếu dữ liệu tương tác, và CTR 0.08 bị lỗi miss khóa Redis — nhóm đang xử lý. Ngoài ra is_open và time_of_day chiếm 0.10 thì thiếu cục bộ, vì 83,2% POI không có thông tin giờ mở cửa.

Cộng lại, khoảng 24% trọng số hiện chưa đóng góp hiệu quả. Đây là hạn chế lớn nhất của baseline và cũng là lý do nhóm tìm tới hướng Learning to Rank."

## Slide 12 — Learning to Rank với LambdaMART
*(~50 giây)*

"Từ baseline tuyến tính, nhóm xây dựng mô hình Learning to Rank, cụ thể là LambdaMART của thư viện LightGBM.

Mô hình nhận đầu vào gồm ngữ cảnh truy vấn, điểm RRF và các đặc trưng của POI, rồi sinh ra một ranking score mới. Điểm khác biệt về mặt phương pháp là LambdaMART tối ưu TRỰC TIẾP hàm nDCG — tức tối ưu đúng chỉ số mình quan tâm — thay vì tối ưu gián tiếp qua một hàm mất mát điểm-theo-điểm như hồi quy.

Tuy nhiên khi đưa LTR vào production, nhóm xây dựng thêm một cơ chế phòng thủ. Nếu số query group nhỏ hơn 30, hoặc tập feature đầu vào không khớp với feature mô hình đã được train, hệ thống sẽ kích hoạt fallback im lặng về Linear Ranking. Cơ chế này ngăn mô hình chạy trong điều kiện dữ liệu không đủ hoặc sai cấu trúc — vì một mô hình học máy bị lệch feature thường không báo lỗi, nó chỉ đơn giản là xếp hạng sai."

## Slide 13 — Nghịch lý textScore & sự phục hồi nDCG
*(~70 giây)*

"Trong quá trình đánh giá, nhóm phát hiện một lỗi hệ thống quan trọng liên quan tới cách xây dựng feature.

Ban đầu, textScore lấy từ OpenSearch thực chất đã chứa sẵn điểm RRF gộp cả Geo và Trending. Sau đó ở bước rerank, hai tín hiệu này lại được cộng vào một lần nữa theo trọng số riêng — tức là hiện tượng double counting, cộng dồn hai lần.

Hệ quả là kết quả đánh giá ban đầu không phản ánh đúng đóng góp của từng tín hiệu. Nhóm khắc phục bằng cách tách riêng bm25_score khỏi fusionScoreNorm ngay trong bước enrichment.

Sau khi sửa, nDCG trong thí nghiệm tương ứng phục hồi từ 0.4720 lên 0.6406.

Một ghi chú quan trọng về tính trung thực của kết quả: sự vượt trội ban đầu của PostGIS với nDCG 0.9291 là ảo — nó do chính lỗi cộng trùng tín hiệu này gây ra, chứ không phải PostGIS thực sự tốt hơn. Bài học rút ra là phải tách bạch rõ nguồn gốc của từng score trước khi so sánh bất kỳ cấu hình nào."

## Slide 14 — Dataset và chia Train/Holdout
*(~65 giây)*

"Tiếp theo là dữ liệu huấn luyện. Dataset cuối cùng gồm 574 nhóm truy vấn — tức QID — tương ứng 9.969 cặp query–POI, trong đó có 993 nhãn dương, chiếm khoảng 10%. Đây là một tập mất cân bằng nhãn khá điển hình của bài toán xếp hạng.

Về độ phủ đặc trưng: điểm RRF, khoảng cách và độ mới đều phủ 100%; BM25 phủ 82%; Vector 58%. Nhưng rating, review_count và price_level phủ 0%.

Đây là giới hạn nghiêm trọng: mô hình mù hoàn toàn về thông tin đánh giá và giá cả, nên bị ép phải học chủ yếu dựa trên vị trí hiển thị và điểm RRF — mà vị trí hiển thị lại chính là thứ nó cần dự đoán.

Về nguyên tắc chống rò rỉ, nhóm chia Train/Holdout cứng theo QID, tuyệt đối không chia theo dòng. Lý do là nếu chia ngẫu nhiên theo dòng, các candidate của cùng một truy vấn sẽ xuất hiện đồng thời ở cả train và holdout, khiến mô hình 'đã nhìn thấy' truy vấn đó và kết quả đánh giá bị thổi phồng."

## Slide 15 — Đánh giá Holdout thực tế
*(~70 giây)*

*[Chỉ vào bảng so sánh]*

"Nhóm đánh giá trên tập Holdout gồm 198 trên 199 nhóm truy vấn hoàn toàn mới, không rò rỉ dữ liệu.

Kết quả: baseline tuyến tính đạt nDCG@5 là 0.4485, MRR 0.3982 và MAP@5 0.3856. LambdaMART đạt nDCG@5 0.4304, MRR 0.3748 và MAP@5 0.3620.

Tức là LambdaMART THUA baseline. Nhóm xin trình bày thẳng kết quả này thay vì chỉ báo cáo con số đẹp, vì nguyên nhân của nó mới là phần đáng giá.

Có hai nguyên nhân. Thứ nhất là Model Limitation — mô hình đói đặc trưng: các tín hiệu chất lượng sống còn như rating có độ phủ 0%, nên mô hình không có gì để học ngoài những thứ baseline vốn đã dùng. Thứ hai là Label Noise — nhãn click bị thiên kiến vị trí, tức position bias, do người dùng có xu hướng click vào top đầu bất kể chất lượng; nhóm chưa khử được thiên kiến này trong dữ liệu.

Kết luận rút ra: xây dựng đúng kiến trúc LTR thôi là chưa đủ. Chất lượng dữ liệu và chất lượng nhãn mới là yếu tố quyết định."

## Slide 16 — Ablation Study
*(~60 giây)*

*[Chỉ lần lượt bốn cột của biểu đồ]*

"Tiếp theo là Ablation Study, nhằm đo đóng góp tích lũy của từng nhóm thành phần trong pipeline.

Cấu hình A — PostGIS thuần — đạt nDCG 0.2635. Khi bổ sung BM25, RRF và Vector k-NN ở cấu hình B/C, kết quả chỉ tăng nhẹ lên 0.2689. Nhưng khi bổ sung 9 tín hiệu ngữ cảnh Spatio-Temporal ở cấu hình D, kết quả nhảy lên 0.4108. Cuối cùng khi thêm LTR ở cấu hình E, kết quả vẫn giữ nguyên 0.4108.

Như vậy khối Enrichment ngữ cảnh — bậc D — mới là động cơ chính tạo ra giá trị khác biệt trong thí nghiệm này.

Một điểm cần nói rõ: Vector k-NN hiện đóng góp bằng 0 trong thí nghiệm này. Điều đó KHÔNG có nghĩa Vector vô giá trị về mặt kiến trúc, mà chỉ cho thấy trên tập ground-truth 3 truy vấn cụ thể này, tín hiệu Vector chưa tạo ra cải thiện đo được. Nhóm cũng lưu ý thí nghiệm chỉ chạy trên 3 truy vấn ground-truth nên nó minh chứng cho luồng kiến trúc, chứ chưa đủ cỡ mẫu để kết luận thống kê."

## Slide 17 — System Error Audit
*(~70 giây)*

"Từ các kết quả trên, nhóm thực hiện System Error Audit để truy nguyên nhân gốc ở mức pipeline. Có ba phát hiện chính.

Thứ nhất là nghịch lý rating: tắt tín hiệu đánh giá đi thì nDCG lại TĂNG 0.0207. Nguyên nhân gốc là giá trị NULL bị mã hóa mặc định thành 0, nên hệ thống vô tình trừng phạt những POI có thật nhưng chưa có dữ liệu rating — coi 'chưa biết' đồng nghĩa với 'điểm kém'. Lỗi này đã sửa: hệ thống hiện cho phép giữ nguyên NULL.

Thứ hai là tín hiệu Graph. Trong các báo cáo cũ, graph_boost từng bị đánh giá là không hoạt động. Kiểm tra lại, nguyên nhân là session_profile không được truyền xuống luồng API. Hiện đã khắc phục, graph_boost hoạt động ổn định và truyền đúng dữ liệu trên luồng `/api/v1/search`.

Thứ ba là CTR: 100% POI có CTR bằng 0. Nguyên nhân gốc có hai phần — registry đọc nhầm khóa Redis phiên bản v2 trong khi dữ liệu thật nằm ở khóa v1, và khoảng 93% POI thiếu dữ liệu district. Vấn đề này đang được xử lý, cần chạy lại pipeline để materialize dữ liệu CTR.

Em xin mời bạn Phụng trình bày phần đánh giá và triển khai."

---

# PHẦN 5–6 · ĐÁNH GIÁ, TRIỂN KHAI & CHỈ ĐƯỜNG
**Người trình bày: Tăng Ngọc Phụng — slide 18→24, ~5 phút**

## Slide 18 — Dữ liệu đánh giá & phương pháp đo
*(~70 giây)*

"Em xin trình bày phần đánh giá và triển khai. Trước hết là nhóm đã đo bằng gì.

Nhóm dùng ba nguồn nhãn liên quan. Nguồn thứ nhất là nhãn chuyên gia theo thang 0 đến 3, trên 3 truy vấn cà phê, công viên và bảo tàng, lấy tâm Bến Thành bán kính 10 km, mỗi truy vấn 2 đến 4 POI. Nguồn thứ hai là nhãn click ngầm định: một sự kiện poi_click hoặc navigation_start được tính là nhãn 1, còn chỉ có impression thì là 0 — đây chính là tập 574 nhóm truy vấn, 9.969 cặp và 993 nhãn dương đã nêu ở phần trước. Nguồn thứ ba là mẫu gán nhãn mở rộng 40 truy vấn nhân 10 ứng viên, tức 400 cặp; tập này đã sinh sẵn nhưng chưa gán nhãn, là việc tiếp theo của nhóm.

Về chỉ số đo, nhóm đo tại k bằng 5 và 10. nDCG@k với gain bằng 2 mũ g trừ 1 và chiết khấu log cơ số 2 của vị trí cộng 1 — chỉ số này quan trọng vì nó phạt việc xếp kết quả tốt xuống dưới. MRR là nghịch đảo thứ hạng của kết quả đúng đầu tiên, phản ánh trải nghiệm 'người dùng thấy ngay cái mình cần'. Cùng với MAP@k, P@k và R@k, trong đó một kết quả được coi là liên quan khi grade lớn hơn hoặc bằng 1.

Về chống rò rỉ dữ liệu, như bạn Phương đã nói, nhóm chia Train/Holdout 80/20 theo QID với seed 42, và mọi đặc trưng đều lấy từ snapshot tại thời điểm phục vụ."

## Slide 19 — Hiệu năng: độ trễ & độ ổn định
*(~70 giây)*

*[Chỉ lần lượt bốn ô số liệu]*

"Tiếp theo là hiệu năng.

Về thời gian xếp hạng, Linear mất 0,83 mili-giây còn LambdaMART mất 9,58 mili-giây trên holdout — tức LTR chậm hơn khoảng 11 lần. Nhưng con số này cần đặt vào bối cảnh: truy xuất trung bình mất khoảng 417 mili-giây, chiếm hơn 97% tổng thời gian. Nghĩa là chi phí của ranking, kể cả LTR, gần như không đáng kể; nút thắt cổ chai thật sự nằm ở tầng Retrieval. Đây là một kết luận quan trọng cho hướng tối ưu tiếp theo — tối ưu ranking sẽ không cải thiện độ trễ cảm nhận được.

Về độ ổn định của mô hình: nDCG@10 của LTR khi cross-validation 5 fold đạt 0,584 với độ lệch chuẩn 0,022, nhưng trên holdout chỉ còn 0,430. Khoảng cách này là dấu hiệu rõ của overfitting trên phân phối truy vấn huấn luyện, củng cố cho nhận định về label noise mà bạn Phương đã nêu.

Cuối cùng, về chỉ mục không gian: geo-distance mất 10,06 mili-giây, H3 ring mất 10,39 mili-giây trên 3.010 POI, với recall của H3 bằng 1,00. Tức là hai cách tương đương nhau cả về tốc độ lẫn độ phủ ở quy mô hiện tại; lợi thế của H3 sẽ chỉ thể hiện khi dữ liệu mở rộng lên nhiều lần."

## Slide 20 — Triển khai production
*(~60 giây)*

*[Chỉ theo luồng từ trái sang phải]*

"Hệ thống đã được triển khai thật, không chỉ chạy trên máy cá nhân.

Luồng đi từ người dùng — trình duyệt và GPS — qua Caddy lo HTTPS với chứng chỉ Let's Encrypt tự động ở cổng 80 và 443, rồi tới Nginx gateway làm nhiệm vụ giới hạn 10 request mỗi giây cho mỗi IP và gắn request-id. Từ gateway, request rẽ về Frontend viết bằng React và MapLibre, hoặc về Backend FastAPI lo Search, Ranking và Directions.

Tầng dữ liệu gồm bốn thành phần: PostGIS 16 là nguồn chuẩn kiêm dự phòng; OpenSearch 2.17 lo BM25, geo và k-NN; Redis 7.4 lo cache, trending và stream; Neo4j 5.24 lưu Knowledge Graph. Backend cũng gọi sang OSRM với 3 profile ô tô, xe máy và đi bộ.

Toàn bộ gồm 12 dịch vụ Docker Compose, chạy trên một VPS amd64 8 vCPU và 24 GB RAM, tiêu thụ khoảng 3,6 GB RAM khi nhàn rỗi.

Về bảo mật mạng, chỉ mở cổng 80 và 443; PostGIS, Redis, OpenSearch và Neo4j đều bind vào 127.0.0.1 nên không truy cập được từ bên ngoài. Hệ thống truy cập công khai qua tên miền sslip.io với chứng chỉ TLS tự động."

## Slide 21 — Độ tin cậy khi vận hành
*(~70 giây)*

"Về độ tin cậy vận hành, nhóm có bốn cơ chế.

Thứ nhất là giới hạn tốc độ hai lớp: Nginx giới hạn 10 request mỗi giây cho mỗi IP với burst 20, vượt thì trả mã 429; backend giới hạn thêm 120 request mỗi phút cho mỗi phiên và lấy IP thật thông qua header proxy — điểm này quan trọng, vì nếu không hệ thống sẽ thấy mọi người dùng đều có chung IP của gateway.

Thứ hai là dự phòng PostGIS: khi OpenSearch lỗi, hệ thống tự chuyển sang pg_trgm kết hợp ST_DWithin, và response ghi rõ trường retrievalBackend là opensearch hay postgis để việc giám sát và đánh giá không bị nhầm lẫn giữa hai chế độ.

Thứ ba là bộ nhớ đệm Redis với TTL phân tầng theo mức độ thay đổi của dữ liệu: tuyến đường cache 6 giờ, có làm tròn tọa độ khoảng 11 mét để tăng tỉ lệ trúng cache; thời tiết 30 phút; trending 4 giờ; và đặc trưng online 7 ngày.

Thứ tư là kiểm thử và CI: hiện có 349 unit test cùng 21 integration và e2e test. Đáng chú ý là cổng chất lượng không chỉ kiểm tra code chạy đúng, mà còn chặn theo nDCG@10 và p95 latency đo trên stack thật.

Về ranker trên production, mặc định hiện tại là Linear 9 tín hiệu, vì nó thắng LambdaMART trên holdout với nDCG@5 0.4485 so với 0.4304. LambdaMART vẫn được đóng gói sẵn và bật được bằng tham số ranker bằng ltr, đồng thời tự fallback về Linear khi nhóm truy vấn nhỏ hơn 30 hoặc khi lệch đặc trưng. Nhóm chọn cấu hình mặc định theo số đo, chứ không theo độ mới của kỹ thuật."

## Slide 22 — Chỉ đường với OSRM tự host
*(~65 giây)*

*[Chỉ vào ba con số hệ số đường vòng]*

"Phần cuối về mặt kỹ thuật là chỉ đường. Nhóm tự host OSRM thay vì gọi dịch vụ ngoài, để chủ động về chi phí và độ trễ.

Với ví dụ Bến Thành đi Thảo Điền, nhóm phát hiện tuyến ô tô và tuyến xe máy chỉ trùng nhau 74 trên 471 điểm. Đây là bằng chứng cho thấy cần một profile xe máy riêng — cấm đường cao tốc và đặt bề rộng 0,8 mét — chứ không thể dùng chung profile ô tô, điều rất đặc thù với giao thông Việt Nam.

Nhóm cũng đo hệ số đường vòng trên 477 cặp điểm: trung vị 1,46, trung bình 1,557 và p90 là 2,09. Nghĩa là khoảng cách chim bay đánh giá thấp quãng đường thực khoảng 1,5 lần, và trong 10% trường hợp xấu nhất là hơn 2 lần. Đây là lý do khoảng cách đường chim bay chỉ nên dùng làm tín hiệu xếp hạng, chứ không nên hiển thị như quãng đường người dùng thực sự phải đi.

Cuối cùng, khi OSRM gặp lỗi, API trả về route bằng null kèm lý do, thay vì trả một tuyến sai hoặc để request treo."

## Slide 23 — Bài học & định hướng tiếp theo
*(~70 giây)*

"Từ toàn bộ quá trình, nhóm rút ra ba nhóm kết luận.

Về Retrieval — phần đã hoàn thiện: tốc độ cao, tách bạch hoàn toàn với Ranking, và hợp nhất RRF hoạt động mượt mà.

Về Ranking và LTR — thực trạng: baseline ổn định nhưng còn khoảng 24% trọng số chưa đóng góp; LTR hoàn thiện về kiến trúc nhưng nhạy với label noise và chất lượng đặc trưng; và hệ thống duy trì safety rule không kích hoạt mô hình khi group size nhỏ hơn 30.

Về hành động tiếp theo, nhóm chọn nguyên tắc 'Data trước AI'. Cụ thể: tạm dừng tối ưu mô hình để giải quyết các vấn đề Data Engineering trước. Hướng thứ nhất là ghi nhận CTR thực tế — xây dựng pipeline thu thập click và impression từ hành vi người dùng thật. Hướng thứ hai là Serving-time Snapshot — ghi lại đầy đủ đặc trưng và trạng thái candidate ngay tại thời điểm phục vụ, để dữ liệu huấn luyện phản ánh đúng ngữ cảnh thực tế và khắc phục feature mismatch. Ngoài ra, nhóm cũng sẽ thực nghiệm riêng để chọn k của RRF trên dữ liệu POI, thay vì chỉ kế thừa giá trị 60 từ nghiên cứu gốc.

Bài học lớn nhất của nhóm là: khi mô hình không cải thiện, nguyên nhân thường nằm ở dữ liệu và nhãn, chứ không nằm ở thuật toán."

## Slide 24 — Cảm ơn
*(~20 giây)*

"Phần trình bày của nhóm 5 đến đây là hết. Mã nguồn được đặt tại GitHub `TangNgocPhung/Final_Nearby_Location_recommendation`, và website demo tại địa chỉ hiển thị trên màn hình, thầy và các bạn có thể thử trực tiếp.

Nhóm em xin cảm ơn thầy và các bạn đã lắng nghe. Nhóm em xin sẵn sàng nhận câu hỏi ạ."

---

# PHỤ LỤC · Chuẩn bị Q&A

Các câu hỏi dưới đây xuất phát từ chính những điểm yếu mà nhóm đã chủ động nêu trong bài — nên khả năng được hỏi là cao.

### 1. "LTR thua baseline thì làm LTR để làm gì?"
Ba ý: (a) kiến trúc LTR đã hoàn chỉnh và đóng gói sẵn, bật bằng `ranker=ltr` — chi phí chuyển đổi bằng 0 khi dữ liệu đủ tốt; (b) chính thí nghiệm LTR mới phơi bày được vấn đề độ phủ feature 0% và position bias, baseline tuyến tính không cho thấy điều đó; (c) nhóm chọn mặc định theo số đo holdout chứ không theo độ mới của kỹ thuật.

### 2. "Vì sao chọn k = 60 trong RRF?"
Trả lời thẳng: kế thừa từ Cormack et al., SIGIR 2009; nhóm CHƯA tự thực nghiệm tối ưu k trên dữ liệu POI. Đây là hạn chế đã ghi nhận, và là một trong các hướng tiếp theo. **Không** bịa lý do lý thuyết.

### 3. "H3 và geo-distance gần như bằng nhau, vậy H3 có thừa không?"
Ở quy mô 3.010 POI thì đúng là tương đương (10,06 so với 10,39 ms, recall 1,00). Lợi thế của H3 là độ phức tạp tra cứu gần như hằng số theo số POI, nên sẽ thể hiện khi dữ liệu mở rộng; ngoài ra H3 còn được dùng làm khóa gom nhóm cho tín hiệu trending theo ô r8.

### 4. "Vì sao tắt rating lại làm nDCG tăng?"
Vì NULL bị mã hóa thành 0 — hệ thống coi 'chưa có dữ liệu' như 'chất lượng kém' và trừng phạt POI hợp lệ. Đã sửa bằng cách giữ nguyên NULL. Đây là ví dụ kinh điển của lỗi missing-value encoding chứ không phải lỗi thuật toán xếp hạng.

### 5. "Position bias là gì và khắc phục thế nào?"
Người dùng click vào top đầu vì nó ở top đầu, không hẳn vì nó liên quan hơn. Mô hình học từ nhãn click sẽ học lại chính thứ tự cũ. Hướng khắc phục chuẩn trong tài liệu: Inverse Propensity Scoring hoặc position-aware click model (ví dụ PBM); điều kiện tiên quyết là phải có Serving-time Snapshot ghi được vị trí hiển thị — đúng việc nhóm đặt làm ưu tiên tiếp theo.

### 6. "Độ trễ 417 ms có chấp nhận được không?"
Hiện chấp nhận được với quy mô demo, nhưng đây là nút thắt thật sự (>97% tổng thời gian). Hướng giảm: cache kết quả retrieval theo ô H3, giảm số ứng viên lấy về từ ~300, và chạy song song 4 kênh retrieval.

### 7. "Nếu OpenSearch chết thì sao?"
Fallback sang PostGIS với `pg_trgm` + `ST_DWithin`, và response ghi rõ `retrievalBackend` để giám sát biết hệ thống đang chạy ở chế độ nào — tránh việc số đo chất lượng của hai chế độ bị trộn lẫn.
