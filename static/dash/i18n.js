// English / Thai strings for the dashboard, plus formatting helpers.
// Every word the page shows comes from this table: the server returns codes, numbers and both spellings of a name, so
// switching the language is one synchronous re-render with no request (see changeLang in app.js).
export const STR = {
  en: {
    title: 'Bangkok Flood Dashboard', workbench: 'Model workbench', phase_before: 'Before flood', phase_during: 'During flood',
    banner_gfs: 'Prototype, not an official warning. Weather: NOAA GFS cycle {cycle}, fetched {fetched} ICT. Flood maps: U-Net emulator of the ANUGA model.',
    banner_demo: 'DEMO MODE: synthetic storm ({demo}), not real weather. Not an official warning.',
    src_live: 'Live', src_demo: 'Demo', src_demo_sub: 'synthetic storm', demo_heavy: 'monsoon trough, heavy rain tomorrow evening',
    demo_showers: 'afternoon showers', demo_ongoing: 'storm in progress', demo_extreme: 'tropical depression',
    banner_offline: 'NOAA weather could not be reached, so a synthetic demo storm is shown instead. Not real weather, not an official warning.',
    banner_stale: 'NOAA is unreachable right now: showing the last forecast fetched ({cycle}). Not an official warning.',
    online: 'Backend online', offline: 'Backend offline', model: 'Model', device: 'Device',
    // layers + toolbar
    L_max: 'Peak flood depth, next 72 h', L_depth: 'Flood depth at selected time', L_cctv: 'CCTV depth heatmap', L_fused: 'Model + CCTV correction', L_model: 'Model only',
    districts: 'Alerts on map', cameras: 'Cameras', buildings: 'Buildings', show_ge: 'Show ≥', heat_radius: 'Heat radius',
    view_2d: '2D', view_3d: '3D', basemap: 'Basemap', bm_streets: 'Streets', bm_satellite: 'Satellite', bm_light: 'Light', bm_dark: 'Dark', bm_osm: 'OpenStreetMap',
    terrain_x: 'Terrain ×', water_x: 'Water height ×', reset_view: 'Reset view', north: 'North up', fullscreen: 'Full screen',
    compare: 'Before / after', compare_off: 'Exit compare', cmp_dry: 'Before flood ⟷ flood', cmp_cctv: 'Model ⟷ model + CCTV', cmp_time: 'Now ⟷ selected time',
    before_lbl: 'BEFORE', after_lbl: 'AFTER', cmp_hint: 'Drag the handle to swipe',
    // loading
    loading: 'Loading…', stage_idle: 'Starting…', stage_fetch: 'Downloading NOAA GFS weather… {d} / {n}', stage_model: 'Running the flood model on 96 h of weather… {s} s',
    stage_wait: 'Preparing the forecast… {s} s',
    // legend + notes
    lg_depth: 'flood water above the normal (dry-weather) level, log scale', lg_cctv: 'CCTV visual estimate, fades with distance from the cameras', lg_alerts: 'Alerts:', lg_cameras: 'Cameras:',
    cls_NORMAL: 'No flooding', cls_WATERLOGGING: 'Waterlogging', cls_FLOODING: 'Flooding', cls_SEVERE_FLOODING: 'Severe flooding', cls_UNUSABLE: 'Unusable frame',
    note_max: 'Deepest flood water in the next 72 h of the NOAA-driven forecast. Flooded patches under about 1 km² are hidden.',
    note_depth: 'Model flood depth at the time on the slider. Press ▶ to animate the forecast.',
    note_cctv: 'Gaussian-kernel interpolation of the newest reading of every camera (weighted by classifier confidence). Readings without a location are left out.',
    note_fused: "Model depth at the slider time, nudged toward each camera's reading within the heat radius (the model-vs-camera difference fades with distance).",
    now: 'Now', play: 'play / pause', max_over: 'max over the next 72 h', hours_abbr: 'h',
    // pixel inspector
    px_title: 'Pixel inspector', px_hint: 'Move the pointer over the map. Zoom in until each 150 m model cell is visible (zoom ≥ 13).',
    px_cell: 'Model cell', px_ground: 'Ground', px_depth: 'Flood depth', px_peak: 'Peak (next 72 h)', px_normal: 'Normal water', px_cn: 'Curve number', px_manning: 'Manning n',
    px_outside: 'Outside the model domain', px_scale: '1 screen px ≈ {m} m', px_cells: 'Model cell ≈ {n} px', zoom: 'Zoom',
    m: 'm', km: 'km', mm: 'mm', mmh: 'mm/h', msl: 'MSL',
    // charts
    c_rain: 'Rain and flooded area', c_past: 'past 24 h shaded', c_rain_lg: 'rain, mm per 15 min', c_area_lg: 'area flooded ≥ 0.15 m, km² (right axis)',
    pt_title: 'Flood depth at a point', pt_hint: 'Click the map to see the forecast flood depth at that spot.', pt_at: 'Flood depth at {lat}, {lon} (near {near})',
    pt_meta: 'Ground {dem} m · normal water {nw} m · peak flood water {pk} m in the next 72 h · dashed lines: watch / warning / severe', pt_out: 'Outside the model domain.',
    click_map: 'Click the map.', mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun',
    // weather (5 points)
    c_weather: 'Weather forecast', wx_src_gfs: 'NOAA GFS · {cycle}', wx_src_demo: 'DEMO', wx_src_wait: 'loading',
    wx_now: 'Now', wx_rain24: 'Rain, next 24 h', wx_rain72: 'Rain, next 72 h', wx_wind: 'Wind', wx_gusts: 'gusts', wx_heavy: 'Heaviest rain',
    wx_wind_v: '{dir} {v} km/h, gusts {g}', wx_heavy_v: '{r} mm/h · {when}', wx_none: 'no rain',
    wx_foot: 'Forecast issued {issued} ICT (model ran in {secs} s). Tide is an assumption (high water at the rain peak).',
    cond_Clear: 'Clear', 'cond_Partly cloudy': 'Partly cloudy', cond_Overcast: 'Overcast', 'cond_Light rain': 'Light rain', 'cond_Moderate rain': 'Moderate rain',
    'cond_Heavy rain': 'Heavy rain', cond_Thunderstorm: 'Thunderstorm',
    dir_N: 'N', dir_NE: 'NE', dir_E: 'E', dir_SE: 'SE', dir_S: 'S', dir_SW: 'SW', dir_W: 'W', dir_NW: 'NW',
    warn_total: 'Total rain {a} mm is above the largest training event ({b} mm): extrapolation.',
    warn_peak: 'Peak {a} mm/15 min is above anything seen in training ({b}): extrapolation.',
    warn_light: 'Forecast rain is very light (strongest hour {a} mm/h; the weakest event the model learned from was {b} mm/h). Treat small flooded patches as unreliable.',
    // alerts (header dropdown)
    al_wait: 'Alerts…', al_none: 'No flood alerts', al_one: 'flood alert', al_many: 'flood alerts', al_all: 'Districts', al_filter: 'Filter districts…',
    al_hint: 'Select a district to zoom to it', al_clear_row: 'no flooding', al_peak_at: 'peak {when}', al_from: 'from {when}', al_now: 'now',
    al_sub_before: 'Next 72 h', al_sub_during: 'Now', al_cctv: 'CCTV', al_source_model: 'model', al_source_mc: 'model + CCTV', al_source_cctv: 'CCTV',
    lv_0: 'No flooding', lv_1: 'Watch', lv_2: 'Warning', lv_3: 'Severe',
    clear_n: '{n} clear', waiting_fc: 'Waiting for the forecast…',
    pop_line_before: '{lvl}: up to {d} m of flood water; from {onset}, peak {peak}.', pop_line_clear: 'No flooding expected in the next 72 h.',
    pop_line_during: 'Model now {d} m ({lvl}); up to {n6} m within 6 h.', pop_vuln: 'Vulnerability {v} ({l}): ground {dem} m, curve number {cn}, {coast} km from the coast.',
    vuln_High: 'high', vuln_Moderate: 'moderate', vuln_Low: 'low',
    pop_cam_line: 'CCTV {id} ({km} km): {cls}, ~{d} m (visual estimate){veh}{ph}', veh: ', vehicles submerged', ph: ', camera position is a placeholder',
    // timeline
    c_timeline: 'Timeline', nothing: 'No flooding expected.', no_events: 'No events.',
    feed_onset: '{name}: water from {onset}, {lvl}, peak {d} m at {peak}',
    feed_cctv: 'CCTV {id} near {name}: {cls}, ~{d} m (visual estimate){veh}',
    feed_rising: 'Model: {name} rising to {lvl} ({d} m) within 6 h',
    // CCTV
    c_cctv: 'CCTV flood readings', live: 'live', offline_tag: 'offline', t_cams: 'Cameras', t_severe: 'Severe', t_fw: 'Flooding / waterlog.', t_newest: 'Newest',
    c_notes: 'Data notes ({n})',
    th_cam: 'Camera', th_class: 'Class', th_depth: 'Depth*', th_time: 'Time ICT', th_model: 'Model', not_mapped: 'not mapped',
    cctv_foot: '* visual estimate from the image classifier ({v}). Database: {f}, reloaded {l}; checked every 15 s.',
    gap_notmapped: '{id} not mapped: {why}.', gap_placeholder: '{ids}: camera position is a placeholder ({m}), so treat the map location as approximate.',
    gap_capture: 'Real capture time unknown for some frames; the ingest time is shown instead.',
    rs_unusable: 'unusable frame (class {cls}, quality {quality})', rs_no_location: 'no camera location', rs_outside: 'outside the model domain',
    rs_same_image: 'same image as {of} (counted once)', rs_duplicate: 'duplicate of {of}',
    nt_csv_missing: '{name} not found', nt_csv_row: 'CSV row {row}: {why}', nt_pipeline_replaced: '{n} CSV row(s) replaced by the classifier pipeline output for the same cameras',
    nt_pipeline_unreadable: 'could not read {name}: {why}',
    import_csv: 'Import readings (CSV)', import_hint: 'Same columns as cctv_image_details.csv (at least cam_id, predicted_class, ingested_ts_utc; plus lat, lon, estimated_water_depth_m, …). Rows are merged into data/cctv/cctv_readings.csv and the alerts update at once.',
    import_btn: 'Import', choose_csv: 'Choose a CSV file first.', importing: 'Importing…', imported: 'Imported {n} row(s).',
    report_manual: 'Report a reading by hand', f_cam: 'Camera / spot id', f_class: 'Class', f_from_depth: 'from depth', f_lat: 'Latitude', f_lon: 'Longitude', f_depth: 'Water depth (m)', f_conf: 'Confidence 0-1', f_notes: 'Notes',
    pick_map: 'Pick on map', pick_click: 'Click the map…', add_reading: 'Add reading', reading_added: 'Reading added.',
    cctv_updated: 'CCTV database updated: alerts refreshed.', cctv_updated_n: 'CCTV database updated ({n} usable reading(s)): alerts refreshed.',
    new_forecast: 'New NOAA forecast loaded ({cycle}).',
    // camera card + popup
    cam_proxy: 'visual flood severity proxy', cam_depth_t: 'Estimated flood depth', cam_mid: 'estimated midpoint', cam_sub: '⚠ vehicle-submerging depth', cam_wpx: 'Water pixels',
    cam_model: 'Model depth here now', cam_district: 'Nearest district', cam_captured: 'Captured', cam_ingested: 'Ingested (capture time unknown)', cam_source: 'Source',
    cam_placeholder: '⚠ position is a placeholder', cam_noimg: 'No photo for this camera', cam_probs: 'Classifier probabilities', cam_fly: 'Zoom to camera', cam_details: 'Details',
    cam_conf: 'Confidence', cam_click_full: 'Click the photo for the full frame', cam_reg: 'Registered camera (no reading yet)', cam_mock: 'mock position',
    p_normal: 'Normal', p_waterlogging: 'Waterlogging', p_flooding: 'Flooding', p_severe: 'Severe flooding', p_unusable: 'Unusable',
    // accuracy + provenance
    c_accuracy: 'Model accuracy', acc_hint: 'U-Net emulator vs the ANUGA model on held-out test scenarios (never seen in training).', acc_rmse: 'Depth RMSE', acc_csi: 'Flood-extent CSI', acc_area: 'Peak area error',
    c_provenance: 'Provenance', prov_weather: 'Weather', prov_weather_gfs: 'NOAA GFS 0.25°, cycle {cycle}', prov_weather_demo: 'synthetic demo storm',
    prov_tide: 'Tide', prov_tide_v: 'assumed high water at rain peak', prov_model: 'Surrogate model', prov_grid: 'Grid', prov_cell: 'Cell size',
    prov_filter: 'Map filter', prov_filter_v: 'patches < {a} km² hidden', prov_cctv: 'CCTV', prov_cctv_v: 'visual proxy, not gauges',
  },
  th: {
    title: 'แดชบอร์ดน้ำท่วมกรุงเทพฯ', workbench: 'ห้องทดลองแบบจำลอง', phase_before: 'ก่อนน้ำท่วม', phase_during: 'ระหว่างน้ำท่วม',
    banner_gfs: 'ต้นแบบ ไม่ใช่การเตือนภัยอย่างเป็นทางการ สภาพอากาศ: NOAA GFS รอบ {cycle} ดึงข้อมูลเมื่อ {fetched} น. แผนที่น้ำท่วม: แบบจำลอง U-Net ที่เลียนแบบ ANUGA',
    banner_demo: 'โหมดสาธิต: พายุจำลอง ({demo}) ไม่ใช่สภาพอากาศจริง ไม่ใช่การเตือนภัยอย่างเป็นทางการ',
    src_live: 'สด', src_demo: 'สาธิต', src_demo_sub: 'พายุจำลอง', demo_heavy: 'ร่องมรสุม ฝนตกหนักเย็นวันพรุ่งนี้',
    demo_showers: 'ฝนตกช่วงบ่าย', demo_ongoing: 'พายุกำลังเกิดขึ้น', demo_extreme: 'ดีเปรสชันเขตร้อน',
    banner_offline: 'เชื่อมต่อ NOAA ไม่ได้ จึงแสดงพายุจำลองเพื่อสาธิตแทน ไม่ใช่สภาพอากาศจริง ไม่ใช่การเตือนภัยอย่างเป็นทางการ',
    banner_stale: 'ขณะนี้เชื่อมต่อ NOAA ไม่ได้: แสดงผลพยากรณ์ล่าสุดที่ดึงมา ({cycle}) ไม่ใช่การเตือนภัยอย่างเป็นทางการ',
    online: 'เชื่อมต่อแบ็กเอนด์แล้ว', offline: 'ขาดการเชื่อมต่อแบ็กเอนด์', model: 'แบบจำลอง', device: 'อุปกรณ์',
    L_max: 'ความลึกน้ำท่วมสูงสุดใน 72 ชม.', L_depth: 'ความลึกน้ำท่วม ณ เวลาที่เลือก', L_cctv: 'แผนที่ความร้อนความลึกจาก CCTV', L_fused: 'แบบจำลอง + ปรับด้วย CCTV', L_model: 'เฉพาะแบบจำลอง',
    districts: 'จุดแจ้งเตือนบนแผนที่', cameras: 'กล้อง', buildings: 'อาคาร', show_ge: 'แสดง ≥', heat_radius: 'รัศมีความร้อน',
    view_2d: '2 มิติ', view_3d: '3 มิติ', basemap: 'แผนที่ฐาน', bm_streets: 'ถนน', bm_satellite: 'ดาวเทียม', bm_light: 'สว่าง', bm_dark: 'มืด', bm_osm: 'OpenStreetMap',
    terrain_x: 'ขยายความสูงภูมิประเทศ ×', water_x: 'ขยายความสูงน้ำ ×', reset_view: 'รีเซ็ตมุมมอง', north: 'หันทิศเหนือขึ้น', fullscreen: 'เต็มจอ',
    compare: 'ก่อน / หลัง', compare_off: 'ออกจากการเปรียบเทียบ', cmp_dry: 'ก่อนน้ำท่วม ⟷ น้ำท่วม', cmp_cctv: 'แบบจำลอง ⟷ แบบจำลอง + CCTV', cmp_time: 'ขณะนี้ ⟷ เวลาที่เลือก',
    before_lbl: 'ก่อน', after_lbl: 'หลัง', cmp_hint: 'ลากแถบเพื่อเลื่อนเปรียบเทียบ',
    loading: 'กำลังโหลด…', stage_idle: 'กำลังเริ่มต้น…', stage_fetch: 'กำลังดาวน์โหลดสภาพอากาศ NOAA GFS… {d} / {n}', stage_model: 'กำลังรันแบบจำลองน้ำท่วมจากสภาพอากาศ 96 ชม.… {s} วินาที',
    stage_wait: 'กำลังเตรียมผลพยากรณ์… {s} วินาที',
    lg_depth: 'น้ำท่วมเหนือระดับน้ำปกติ (ช่วงอากาศแห้ง) มาตราส่วนลอการิทึม', lg_cctv: 'ค่าประมาณจากภาพ CCTV จางลงตามระยะห่างจากกล้อง', lg_alerts: 'การแจ้งเตือน:', lg_cameras: 'กล้อง:',
    cls_NORMAL: 'ไม่มีน้ำท่วม', cls_WATERLOGGING: 'น้ำรอการระบาย', cls_FLOODING: 'น้ำท่วม', cls_SEVERE_FLOODING: 'น้ำท่วมรุนแรง', cls_UNUSABLE: 'ภาพใช้ไม่ได้',
    note_max: 'น้ำท่วมลึกที่สุดใน 72 ชม. ข้างหน้าจากผลพยากรณ์ที่ขับเคลื่อนด้วยข้อมูล NOAA ซ่อนพื้นที่น้ำท่วมที่เล็กกว่าประมาณ 1 ตร.กม.',
    note_depth: 'ความลึกน้ำท่วมจากแบบจำลอง ณ เวลาบนแถบเลื่อน กด ▶ เพื่อเล่นภาพเคลื่อนไหว',
    note_cctv: 'ประมาณค่าด้วยเคอร์เนลเกาส์เซียนจากค่าล่าสุดของกล้องแต่ละตัว (ถ่วงน้ำหนักด้วยความมั่นใจของตัวจำแนก) ค่าที่ไม่มีตำแหน่งจะถูกตัดออก',
    note_fused: 'ความลึกจากแบบจำลอง ณ เวลาบนแถบเลื่อน ปรับเข้าหาค่าของกล้องภายในรัศมีความร้อน (ผลต่างระหว่างแบบจำลองกับกล้องจะจางลงตามระยะทาง)',
    now: 'ขณะนี้', play: 'เล่น / หยุด', max_over: 'ค่าสูงสุดใน 72 ชม. ข้างหน้า', hours_abbr: 'ชม.',
    px_title: 'ตรวจสอบระดับพิกเซล', px_hint: 'เลื่อนเมาส์บนแผนที่ ซูมเข้าจนเห็นเซลล์แบบจำลองขนาด 150 ม. ทีละช่อง (ซูม ≥ 13)',
    px_cell: 'เซลล์แบบจำลอง', px_ground: 'ระดับพื้นดิน', px_depth: 'ความลึกน้ำท่วม', px_peak: 'สูงสุด (72 ชม. ข้างหน้า)', px_normal: 'ระดับน้ำปกติ', px_cn: 'ค่า Curve number', px_manning: 'ค่า Manning n',
    px_outside: 'อยู่นอกขอบเขตแบบจำลอง', px_scale: '1 พิกเซลหน้าจอ ≈ {m} ม.', px_cells: 'เซลล์แบบจำลอง ≈ {n} พิกเซล', zoom: 'ซูม',
    m: 'ม.', km: 'กม.', mm: 'มม.', mmh: 'มม./ชม.', msl: 'รทก.',
    c_rain: 'ฝนและพื้นที่น้ำท่วม', c_past: 'แรเงา 24 ชม. ที่ผ่านมา', c_rain_lg: 'ฝน มม. ต่อ 15 นาที', c_area_lg: 'พื้นที่น้ำท่วม ≥ 0.15 ม. ตร.กม. (แกนขวา)',
    pt_title: 'ความลึกน้ำท่วมที่จุดที่เลือก', pt_hint: 'คลิกที่แผนที่เพื่อดูความลึกน้ำท่วมที่พยากรณ์ ณ จุดนั้น', pt_at: 'ความลึกน้ำท่วมที่ {lat}, {lon} (ใกล้เขต{near})',
    pt_meta: 'พื้นดิน {dem} ม. · ระดับน้ำปกติ {nw} ม. · น้ำท่วมสูงสุด {pk} ม. ใน 72 ชม. ข้างหน้า · เส้นประ: เฝ้าระวัง / เตือนภัย / รุนแรง', pt_out: 'อยู่นอกขอบเขตแบบจำลอง',
    click_map: 'คลิกที่แผนที่', mon: 'จ.', tue: 'อ.', wed: 'พ.', thu: 'พฤ.', fri: 'ศ.', sat: 'ส.', sun: 'อา.',
    c_weather: 'พยากรณ์อากาศ', wx_src_gfs: 'NOAA GFS · {cycle}', wx_src_demo: 'สาธิต', wx_src_wait: 'กำลังโหลด',
    wx_now: 'ขณะนี้', wx_rain24: 'ฝน 24 ชม. ข้างหน้า', wx_rain72: 'ฝน 72 ชม. ข้างหน้า', wx_wind: 'ลม', wx_gusts: 'กระโชก', wx_heavy: 'ฝนหนักที่สุด',
    wx_wind_v: '{dir} {v} กม./ชม. กระโชก {g}', wx_heavy_v: '{r} มม./ชม. · {when}', wx_none: 'ไม่มีฝน',
    wx_foot: 'ออกผลพยากรณ์เมื่อ {issued} น. (แบบจำลองรันใน {secs} วินาที) ระดับน้ำขึ้นน้ำลงเป็นข้อสมมติ (น้ำขึ้นสูงสุดตรงกับช่วงฝนสูงสุด)',
    cond_Clear: 'แจ่มใส', 'cond_Partly cloudy': 'มีเมฆบางส่วน', cond_Overcast: 'มีเมฆมาก', 'cond_Light rain': 'ฝนเล็กน้อย', 'cond_Moderate rain': 'ฝนปานกลาง',
    'cond_Heavy rain': 'ฝนตกหนัก', cond_Thunderstorm: 'พายุฝนฟ้าคะนอง',
    dir_N: 'เหนือ', dir_NE: 'ตะวันออกเฉียงเหนือ', dir_E: 'ตะวันออก', dir_SE: 'ตะวันออกเฉียงใต้', dir_S: 'ใต้', dir_SW: 'ตะวันตกเฉียงใต้', dir_W: 'ตะวันตก', dir_NW: 'ตะวันตกเฉียงเหนือ',
    warn_total: 'ปริมาณฝนรวม {a} มม. สูงกว่าเหตุการณ์ที่ใหญ่ที่สุดในชุดฝึก ({b} มม.): เป็นการคาดการณ์นอกช่วงข้อมูล',
    warn_peak: 'ความเข้มฝนสูงสุด {a} มม./15 นาที สูงกว่าที่เคยพบในชุดฝึก ({b}): เป็นการคาดการณ์นอกช่วงข้อมูล',
    warn_light: 'ฝนที่พยากรณ์เบามาก (ชั่วโมงที่หนักที่สุด {a} มม./ชม. ขณะที่เหตุการณ์ที่เบาที่สุดที่แบบจำลองเรียนรู้คือ {b} มม./ชม.) ควรถือว่าพื้นที่น้ำท่วมเล็ก ๆ เชื่อถือไม่ได้',
    al_wait: 'การแจ้งเตือน…', al_none: 'ไม่มีการแจ้งเตือนน้ำท่วม', al_one: 'การแจ้งเตือนน้ำท่วม', al_many: 'การแจ้งเตือนน้ำท่วม', al_all: 'เขตทั้งหมด', al_filter: 'ค้นหาเขต…',
    al_hint: 'เลือกเขตเพื่อซูมไปที่เขตนั้น', al_clear_row: 'ไม่มีน้ำท่วม', al_peak_at: 'สูงสุด {when}', al_from: 'ตั้งแต่ {when}', al_now: 'ขณะนี้',
    al_sub_before: '72 ชม. ข้างหน้า', al_sub_during: 'ขณะนี้', al_cctv: 'CCTV', al_source_model: 'แบบจำลอง', al_source_mc: 'แบบจำลอง + CCTV', al_source_cctv: 'CCTV',
    lv_0: 'ไม่มีน้ำท่วม', lv_1: 'เฝ้าระวัง', lv_2: 'เตือนภัย', lv_3: 'รุนแรง',
    clear_n: 'ปกติ {n}', waiting_fc: 'กำลังรอผลพยากรณ์…',
    pop_line_before: '{lvl}: น้ำท่วมสูงสุด {d} ม. เริ่มตั้งแต่ {onset} สูงสุด {peak}', pop_line_clear: 'ไม่คาดว่าจะเกิดน้ำท่วมใน 72 ชม. ข้างหน้า',
    pop_line_during: 'แบบจำลองขณะนี้ {d} ม. ({lvl}) ใน 6 ชม. ข้างหน้าสูงสุด {n6} ม.', pop_vuln: 'ความเปราะบาง{l} ({v}): พื้นดินสูง {dem} ม. ค่า curve number {cn} ห่างชายฝั่ง {coast} กม.',
    vuln_High: 'สูง', vuln_Moderate: 'ปานกลาง', vuln_Low: 'ต่ำ',
    pop_cam_line: 'CCTV {id} ({km} กม.): {cls} ประมาณ {d} ม. (ประมาณจากภาพ){veh}{ph}', veh: ' รถจมน้ำ', ph: ' ตำแหน่งกล้องเป็นค่าสมมติ',
    c_timeline: 'ไทม์ไลน์', nothing: 'ไม่คาดว่าจะมีน้ำท่วม', no_events: 'ไม่มีเหตุการณ์',
    feed_onset: '{name}: น้ำเริ่มเข้าตั้งแต่ {onset} ระดับ{lvl} สูงสุด {d} ม. เวลา {peak}',
    feed_cctv: 'CCTV {id} ใกล้เขต{name}: {cls} ประมาณ {d} ม. (ประมาณจากภาพ){veh}',
    feed_rising: 'แบบจำลอง: {name} กำลังขึ้นสู่ระดับ{lvl} ({d} ม.) ภายใน 6 ชม.',
    c_cctv: 'ค่าน้ำท่วมจากกล้อง CCTV', live: 'สด', offline_tag: 'ออฟไลน์', t_cams: 'กล้อง', t_severe: 'รุนแรง', t_fw: 'ท่วม / รอระบาย', t_newest: 'ล่าสุด',
    c_notes: 'หมายเหตุข้อมูล ({n})',
    th_cam: 'กล้อง', th_class: 'ระดับ', th_depth: 'ความลึก*', th_time: 'เวลา', th_model: 'แบบจำลอง', not_mapped: 'ไม่ได้แสดงบนแผนที่',
    cctv_foot: '* ค่าประมาณจากตัวจำแนกภาพ ({v}) ฐานข้อมูล: {f} โหลดเมื่อ {l} ตรวจสอบทุก 15 วินาที',
    gap_notmapped: '{id} ไม่ได้แสดงบนแผนที่: {why}', gap_placeholder: '{ids}: ตำแหน่งกล้องเป็นค่าสมมติ ({m}) ตำแหน่งบนแผนที่จึงเป็นค่าโดยประมาณ',
    gap_capture: 'ไม่ทราบเวลาถ่ายจริงของบางภาพ จึงแสดงเวลานำเข้าแทน',
    rs_unusable: 'ภาพใช้ไม่ได้ (ระดับ {cls} คุณภาพ {quality})', rs_no_location: 'ไม่มีตำแหน่งกล้อง', rs_outside: 'อยู่นอกขอบเขตแบบจำลอง',
    rs_same_image: 'เป็นภาพเดียวกับ {of} (นับครั้งเดียว)', rs_duplicate: 'ซ้ำกับ {of}',
    nt_csv_missing: 'ไม่พบไฟล์ {name}', nt_csv_row: 'แถว CSV {row}: {why}', nt_pipeline_replaced: 'แทนที่ {n} แถวของ CSV ด้วยผลจากตัวจำแนกภาพของกล้องเดียวกัน',
    nt_pipeline_unreadable: 'อ่านไฟล์ {name} ไม่ได้: {why}',
    import_csv: 'นำเข้าค่าจากไฟล์ CSV', import_hint: 'คอลัมน์เหมือน cctv_image_details.csv (อย่างน้อย cam_id, predicted_class, ingested_ts_utc และ lat, lon, estimated_water_depth_m …) แถวข้อมูลจะถูกรวมเข้า data/cctv/cctv_readings.csv และการแจ้งเตือนจะอัปเดตทันที',
    import_btn: 'นำเข้า', choose_csv: 'กรุณาเลือกไฟล์ CSV ก่อน', importing: 'กำลังนำเข้า…', imported: 'นำเข้าแล้ว {n} แถว',
    report_manual: 'รายงานค่าด้วยตนเอง', f_cam: 'รหัสกล้อง / จุดสังเกต', f_class: 'ระดับ', f_from_depth: 'ตามความลึก', f_lat: 'ละติจูด', f_lon: 'ลองจิจูด', f_depth: 'ความลึกน้ำ (ม.)', f_conf: 'ความมั่นใจ 0-1', f_notes: 'หมายเหตุ',
    pick_map: 'เลือกบนแผนที่', pick_click: 'คลิกที่แผนที่…', add_reading: 'เพิ่มค่า', reading_added: 'เพิ่มค่าแล้ว',
    cctv_updated: 'อัปเดตฐานข้อมูล CCTV แล้ว: รีเฟรชการแจ้งเตือนแล้ว', cctv_updated_n: 'อัปเดตฐานข้อมูล CCTV แล้ว (ใช้งานได้ {n} ค่า): รีเฟรชการแจ้งเตือนแล้ว',
    new_forecast: 'โหลดผลพยากรณ์ NOAA ชุดใหม่แล้ว ({cycle})',
    cam_proxy: 'ตัวแทนความรุนแรงน้ำท่วมจากภาพ', cam_depth_t: 'ความลึกน้ำท่วมโดยประมาณ', cam_mid: 'ค่ากลางโดยประมาณ', cam_sub: '⚠ ลึกพอจะท่วมรถ', cam_wpx: 'พิกเซลที่เป็นน้ำ',
    cam_model: 'ความลึกจากแบบจำลอง ณ จุดนี้ตอนนี้', cam_district: 'เขตที่ใกล้ที่สุด', cam_captured: 'เวลาถ่าย', cam_ingested: 'เวลานำเข้า (ไม่ทราบเวลาถ่าย)', cam_source: 'แหล่งที่มา',
    cam_placeholder: '⚠ ตำแหน่งเป็นค่าสมมติ', cam_noimg: 'ไม่มีภาพของกล้องนี้', cam_probs: 'ความน่าจะเป็นจากตัวจำแนก', cam_fly: 'ซูมไปที่กล้อง', cam_details: 'รายละเอียด',
    cam_conf: 'ความมั่นใจ', cam_click_full: 'คลิกภาพเพื่อดูเต็มเฟรม', cam_reg: 'กล้องที่ขึ้นทะเบียน (ยังไม่มีค่า)', cam_mock: 'ตำแหน่งจำลอง',
    p_normal: 'ปกติ', p_waterlogging: 'น้ำรอการระบาย', p_flooding: 'น้ำท่วม', p_severe: 'น้ำท่วมรุนแรง', p_unusable: 'ใช้ไม่ได้',
    c_accuracy: 'ความแม่นยำของแบบจำลอง', acc_hint: 'U-Net เทียบกับแบบจำลอง ANUGA บนสถานการณ์ทดสอบที่ไม่เคยเห็นตอนฝึก', acc_rmse: 'RMSE ความลึก', acc_csi: 'CSI ขอบเขตน้ำท่วม', acc_area: 'ความคลาดเคลื่อนพื้นที่สูงสุด',
    c_provenance: 'ที่มาของข้อมูล', prov_weather: 'สภาพอากาศ', prov_weather_gfs: 'NOAA GFS 0.25° รอบ {cycle}', prov_weather_demo: 'พายุจำลองเพื่อสาธิต',
    prov_tide: 'น้ำขึ้นน้ำลง', prov_tide_v: 'สมมติว่าน้ำขึ้นสูงสุดตรงกับฝนสูงสุด', prov_model: 'แบบจำลองตัวแทน', prov_grid: 'กริด', prov_cell: 'ขนาดเซลล์',
    prov_filter: 'ตัวกรองแผนที่', prov_filter_v: 'ซ่อนพื้นที่ < {a} ตร.กม.', prov_cctv: 'CCTV', prov_cctv_v: 'ตัวแทนจากภาพ ไม่ใช่เครื่องวัด',
  },
};

export const TH_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];
export const EN_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DOW = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];

let lang = 'en';
try { const s = localStorage.getItem('fd_lang'); if (s === 'th' || s === 'en') lang = s; else if ((navigator.language || '').toLowerCase().startsWith('th')) lang = 'th'; } catch (e) {}
try { const q = new URLSearchParams(location.search).get('lang'); if (q === 'th' || q === 'en') lang = q; } catch (e) {}

export const getLang = () => lang;
export function setLang(l) {
  lang = l === 'th' ? 'th' : 'en';
  try { localStorage.setItem('fd_lang', lang); } catch (e) {}
  document.documentElement.lang = lang;
  document.title = t('title');
}
export function t(key, vars) {
  let s = (STR[lang] && STR[lang][key]) ?? STR.en[key] ?? key;
  if (vars) for (const k in vars) s = s.replaceAll('{' + k + '}', vars[k]);
  return s;
}
export const months = () => (lang === 'th' ? TH_MONTHS : EN_MONTHS);
/** 'YYYY-MM-DD HH:MM' (ICT, as the server sends it) -> '10 Oct 14:30' / '10 ต.ค. 14:30' */
export function fmtTime(s) {
  if (!s) return '–';
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(s);
  if (!m) return s;
  return `${+m[3]} ${months()[+m[2] - 1]} ${m[4]}:${m[5]}`;
}
export function dowOf(dateStr) { return t(DOW[new Date(dateStr + 'T12:00:00').getDay()]); }
export function num(v, d = 2) { return v == null || isNaN(v) ? '–' : Number(v).toFixed(d); }

/** Apply translations to every [data-i18n], [data-i18n-title], [data-i18n-ph], [data-i18n-html] element. */
export function applyStatic(root = document) {
  root.querySelectorAll('[data-i18n]').forEach((e) => { e.textContent = t(e.dataset.i18n); });
  root.querySelectorAll('[data-i18n-html]').forEach((e) => { e.innerHTML = t(e.dataset.i18nHtml); });
  root.querySelectorAll('[data-i18n-title]').forEach((e) => { e.title = t(e.dataset.i18nTitle); e.setAttribute('aria-label', e.title); });
  root.querySelectorAll('[data-i18n-ph]').forEach((e) => { e.placeholder = t(e.dataset.i18nPh); });
}
