from app import streetview
from app.streetview import angle_difference, bearing_degrees, choose_views

# Khách sạn Trung Mai, 785 Nguyễn Trãi (toạ độ thật trong DB).
POI_LAT, POI_LNG = 10.7528584, 106.6591951
# ~1 m theo vĩ độ.
DLAT = 1 / 111_320


def image(id_, lat, lng, *, pano=False, compass=None, captured_ms=1_700_000_000_000):
    return {
        "id": id_,
        "is_pano": pano,
        "captured_at": captured_ms,
        "computed_compass_angle": compass,
        "computed_geometry": {"type": "Point", "coordinates": [lng, lat]},
        "creator": {"username": "tester"},
        "thumb_1024_url": f"https://example.test/{id_}.jpg",
    }


def test_bearing_bon_huong_chinh():
    assert round(bearing_degrees(0, 0, 1, 0)) == 0
    assert round(bearing_degrees(0, 0, 0, 1)) == 90
    assert round(bearing_degrees(0, 0, -1, 0)) == 180
    assert round(bearing_degrees(0, 0, 0, -1)) == 270


def test_angle_difference_qua_diem_0():
    assert angle_difference(350, 10) == 20
    assert angle_difference(10, 350) == 20
    assert angle_difference(0, 180) == 180


def test_pano_chon_gan_nhat_bat_ke_huong():
    items = [
        image("xa", POI_LAT - 30 * DLAT, POI_LNG, pano=True, compass=0),
        image("gan", POI_LAT - 15 * DLAT, POI_LNG, pano=True, compass=180),
    ]
    views = choose_views(items, POI_LAT, POI_LNG)
    assert views["pano"]["imageId"] == "gan"
    # Ảnh ở phía NAM của quán → quán nằm ở hướng Bắc.
    assert round(views["pano"]["bearingToPoi"]) == 0
    assert "_capturedMs" not in views["pano"]


def test_anh_moi_hon_thang_anh_cu_gan_hon_chut_it():
    items = [
        image("cu", POI_LAT - 12 * DLAT, POI_LNG, pano=True, captured_ms=1_600_000_000_000),
        image("moi", POI_LAT - 16 * DLAT, POI_LNG, pano=True, captured_ms=1_750_000_000_000),
    ]
    assert choose_views(items, POI_LAT, POI_LNG)["pano"]["imageId"] == "moi"


def test_anh_thuong_phai_nhin_ve_phia_quan():
    south = POI_LAT - 10 * DLAT
    items = [
        # Gần hơn nhưng quay lưng lại quán (nhìn về hướng Nam).
        image("quay_lung", POI_LAT - 5 * DLAT, POI_LNG, compass=180),
        # Nhìn về hướng Bắc, lệch 20° — vẫn trong dung sai.
        image("nhin_quan", south, POI_LNG, compass=20),
    ]
    views = choose_views(items, POI_LAT, POI_LNG)
    assert views["facing"]["imageId"] == "nhin_quan"
    assert views["pano"] is None


def test_bo_anh_ngoai_ban_kinh_va_thieu_huong():
    items = [
        image("xa_qua", POI_LAT - 100 * DLAT, POI_LNG, pano=True),
        image("khong_huong", POI_LAT - 10 * DLAT, POI_LNG, compass=None),
        image("sat_toa_do", POI_LAT - 1 * DLAT, POI_LNG, compass=0),
    ]
    assert choose_views(items, POI_LAT, POI_LNG) == {"pano": None, "facing": None}


def test_khong_co_token_la_unavailable(monkeypatch):
    monkeypatch.setattr(streetview.settings, "mapillary_client_token", "")
    result = streetview.street_views("poi-1", POI_LAT, POI_LNG)
    assert result["status"] == "unavailable"


def test_loi_mang_khong_ghi_cache(monkeypatch):
    monkeypatch.setattr(streetview.settings, "mapillary_client_token", "MLY|x|y")
    monkeypatch.setattr(streetview, "_search_images", lambda lat, lng: None)
    streetview._cache.clear()
    assert streetview.street_views("poi-2", POI_LAT, POI_LNG)["status"] == "unavailable"
    assert "poi-2" not in streetview._cache


def test_empty_duoc_cache(monkeypatch):
    monkeypatch.setattr(streetview.settings, "mapillary_client_token", "MLY|x|y")
    monkeypatch.setattr(streetview, "_search_images", lambda lat, lng: [])
    streetview._cache.clear()
    result = streetview.street_views("poi-3", POI_LAT, POI_LNG)
    assert result["status"] == "empty"
    assert "poi-3" in streetview._cache


def _tile_with_points(tx, ty, points):
    """Dựng một vector tile giả có lớp `image`, mỗi điểm (lat, lng, props)."""
    tile = streetview._vector_tile_class()()
    layer = tile.layers.add(name="image", version=2, extent=4096)
    keys: list[str] = []
    for lat, lng, props in points:
        feature = layer.features.add(type=1)
        x, y = streetview.tile_xy(lat, lng)
        px, py = round((x - tx) * 4096), round((y - ty) * 4096)
        feature.geometry.extend([9, (px << 1) ^ (px >> 31), (py << 1) ^ (py >> 31)])
        for key, value in props.items():
            if key not in keys:
                keys.append(key)
                layer.keys.append(key)
            encoded = layer.values.add()
            if isinstance(value, bool):
                encoded.bool_value = value
            elif isinstance(value, int):
                encoded.int_value = value
            else:
                encoded.double_value = value
            feature.tags.extend([keys.index(key), len(layer.values) - 1])
    return tile


def test_points_in_tile_loc_theo_bbox_va_giai_ma_thuoc_tinh():
    x, y = streetview.tile_xy(POI_LAT, POI_LNG)
    tx, ty = int(x), int(y)
    tile = _tile_with_points(
        tx,
        ty,
        [
            (POI_LAT - 10 * DLAT, POI_LNG, {"id": 11, "is_pano": True, "compass_angle": 90.5}),
            (POI_LAT - 500 * DLAT, POI_LNG, {"id": 22, "is_pano": False}),
        ],
    )
    west, south, east, north = map(float, streetview.bbox_around(POI_LAT, POI_LNG, 60).split(","))
    points = streetview.points_in_tile(tile, tx, ty, south, west, north, east)
    assert [p["id"] for p in points] == [11]
    assert points[0]["is_pano"] is True
    assert points[0]["compass_angle"] == 90.5
    lng, lat = points[0]["geometry"]["coordinates"]
    # Sai số lượng tử hoá của extent 4096 ở z14: dưới 1 m.
    assert streetview.distance_meters(lat, lng, POI_LAT - 10 * DLAT, POI_LNG) < 1.0


def test_loc_tho_rong_tay_hon_loc_chat():
    # Hướng gốc lệch 50° — ngoài dung sai chặt 35° nhưng vẫn vào vòng hỏi chi
    # tiết, vì hướng hiệu chỉnh có thể khác hướng gốc hàng chục độ.
    items = [image("lech_50", POI_LAT - 10 * DLAT, POI_LNG, compass=50)]
    assert streetview.candidate_ids(items, POI_LAT, POI_LNG) == ["lech_50"]
    assert choose_views(items, POI_LAT, POI_LNG)["facing"] is None


def test_anh_kem_chat_luong_xep_sau_anh_dat_du_xa_hon():
    # Số liệu thật ở Trung Mai: ảnh đêm nhoè 0,06 cách 15 m, ảnh chiều 0,65 cách 31 m.
    near_blurry = image("dem_nhoe", POI_LAT - 15 * DLAT, POI_LNG, compass=0)
    far_sharp = image("chieu_ro", POI_LAT - 31 * DLAT, POI_LNG, compass=0)
    near_blurry["quality_score"] = 0.06
    far_sharp["quality_score"] = 0.65
    views = choose_views([near_blurry, far_sharp], POI_LAT, POI_LNG)
    assert views["facing"]["imageId"] == "chieu_ro"
    assert "_quality" not in views["facing"]
    # Chỉ còn ảnh kém thì vẫn dùng, không bỏ trống.
    assert choose_views([near_blurry], POI_LAT, POI_LNG)["facing"]["imageId"] == "dem_nhoe"


def test_anh_qua_cu_thua_anh_moi_xa_hon():
    # Số liệu thật ở Trung Mai: ảnh 2014 cách 23 m so với ảnh 2025 cách 31 m.
    old = image("2014", POI_LAT - 23 * DLAT, POI_LNG, compass=0, captured_ms=1_417_900_000_000)
    new = image("2025", POI_LAT - 31 * DLAT, POI_LNG, compass=0, captured_ms=1_756_300_000_000)
    assert choose_views([old, new], POI_LAT, POI_LNG)["facing"]["imageId"] == "2025"
