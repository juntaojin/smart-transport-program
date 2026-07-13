type PointTuple = [number, number];

interface RoadModelV8 {
  metadata: {
    name: string;
    coordinate_system: string;
    image_width: number;
    image_height: number;
    origin: string;
    x_axis: string;
    y_axis: string;
    status: string;
    notes: string;
    extent: { width: number; height: number };
  };
  nodes: { id: string; x: number; y: number; type?: string; name?: string; confidence?: number }[];
  roads: {
    id: string;
    from: string;
    to: string;
    name: string;
    class: string;
    lanes: number;
    direction: string;
    confidence: number;
    centerline: PointTuple[];
  }[];
  lane_markings: {
    id: string;
    name: string;
    style: 'solid' | 'dashed';
    direction: string;
    points: PointTuple[];
  }[];
  crosswalks: {
    id: string;
    width: number;
    stripe_count: number;
    points: PointTuple[];
  }[];
  road_arrows: {
    id: string;
    x: number;
    y: number;
    angle: number;
    size: number;
  }[];
}

const roadModelV8: RoadModelV8 = {
  metadata: {
    name: '学校沙盘道路模型 v8',
    coordinate_system: 'source_image_pixel_xy',
    image_width: 954,
    image_height: 740,
    origin: 'top_left',
    x_axis: 'right',
    y_axis: 'down',
    status: 'readonly_ipm_whiteboard',
    notes: '由 testdata/v8 CSV 建模导入，用于前端 IPM 白板只读展示。',
    extent: {
      width: 954,
      height: 740,
    },
  },
  nodes: [],
  roads: [
    { id: 'R02', from: 'N02', to: 'N03', name: '北侧主路东段', class: 'arterial', lanes: 4, direction: 'two_way', confidence: 0.93, centerline: [[20, 90], [880, 90]] },
    { id: 'R03', from: 'N01', to: 'N17', name: '西侧边界纵路', class: 'collector', lanes: 2, direction: 'two_way', confidence: 0.92, centerline: [[20, 90], [20, 680]] },
    { id: 'R04', from: 'N02', to: 'N18', name: '中央纵向主路', class: 'arterial', lanes: 4, direction: 'two_way', confidence: 0.95, centerline: [[820, 220], [820, 450]] },
    { id: 'R05', from: 'N03', to: 'N19', name: '东侧边界纵路', class: 'collector', lanes: 2, direction: 'two_way', confidence: 0.92, centerline: [[880, 90], [880, 680]] },
    { id: 'R11', from: 'N14', to: 'N15', name: '中部东西主路中央段', class: 'arterial', lanes: 4, direction: 'two_way', confidence: 0.97, centerline: [[20, 680], [880, 680]] },
    { id: 'R12', from: 'N15', to: 'N16', name: '中部东西主路东段', class: 'arterial', lanes: 4, direction: 'two_way', confidence: 0.96, centerline: [[820, 670], [820, 600], [880, 600]] },
    { id: 'R13', from: 'N04', to: 'N20', name: '停车场西侧外环', class: 'parking_loop', lanes: 1, direction: 'one_way', confidence: 0.92, centerline: [[192.399, 221.33], [111.017, 221.801], [110, 470], [190, 470]] },
    { id: 'R15', from: 'N22', to: 'N23', name: '停车场中央矩形环路西侧', class: 'parking_loop', lanes: 1, direction: 'one_way', confidence: 0.9, centerline: [[270, 220], [270, 470]] },
    { id: 'R16', from: 'N23', to: 'N22', name: '停车场中央矩形环路东侧', class: 'parking_loop', lanes: 1, direction: 'one_way', confidence: 0.9, centerline: [[270, 470], [410, 470], [414.091, 219.073], [270, 220]] },
    { id: 'R19', from: 'N24', to: 'N25', name: '商务区北侧弧段', class: 'urban_loop', lanes: 2, direction: 'one_way_loop', confidence: 0.9, centerline: [[560, 220], [720, 220]] },
    { id: 'R20', from: 'N25', to: 'N26', name: '商务区东侧弯道', class: 'urban_loop', lanes: 2, direction: 'one_way_loop', confidence: 0.92, centerline: [[719.264, 221.801], [720, 450]] },
    { id: 'R21', from: 'N26', to: 'N27', name: '商务区南侧直段', class: 'urban_loop', lanes: 2, direction: 'one_way_loop', confidence: 0.95, centerline: [[720, 450], [560, 450]] },
    { id: 'R22', from: 'N27', to: 'N24', name: '商务区西侧弯道', class: 'urban_loop', lanes: 2, direction: 'one_way_loop', confidence: 0.9, centerline: [[560, 450], [560, 220]] },
    { id: 'R23', from: 'N28', to: 'N29', name: '消防医院北侧服务路', class: 'service_loop', lanes: 2, direction: 'two_way', confidence: 0.95, centerline: [[560, 670], [560, 600]] },
    { id: 'R24', from: 'N29', to: 'N30', name: '消防医院东侧弯段', class: 'service_loop', lanes: 1, direction: 'one_way_loop', confidence: 0.93, centerline: [[563.842, 600.63], [720, 600], [720, 670]] },
    { id: 'R25', from: 'N30', to: 'N31', name: '消防医院南侧服务路', class: 'service_loop', lanes: 1, direction: 'one_way_loop', confidence: 0.93, centerline: [[110, 680], [110, 600]] },
    { id: 'R26', from: 'N31', to: 'N28', name: '消防医院西侧弯段', class: 'service_loop', lanes: 1, direction: 'one_way_loop', confidence: 0.93, centerline: [[110, 600], [410, 600], [410, 680]] },
    { id: 'R31', from: 'N33', to: 'N34', name: 'N33-N34连接路', class: 'service', lanes: 2, direction: 'two_way', confidence: 1, centerline: [[190, 220], [190, 470]] },
    { id: 'R32', from: 'N35', to: 'N18', name: 'N35-N18连接路', class: 'service', lanes: 2, direction: 'two_way', confidence: 1, centerline: [[880, 450], [820, 450]] },
    { id: 'R33', from: 'N02', to: 'N36', name: 'N02-N36连接路', class: 'road', lanes: 2, direction: 'two_way', confidence: 1, centerline: [[820, 220], [880, 220]] },
  ],
  lane_markings: [
    { id: 'LM01', name: '', style: 'solid', direction: 'forward', points: [[70, 220], [70, 470]] },
    { id: 'LM02', name: '', style: 'solid', direction: 'forward', points: [[230, 220], [230, 470]] },
    { id: 'LM03', name: '', style: 'solid', direction: 'forward', points: [[110, 540], [410, 540]] },
    { id: 'LM04', name: '', style: 'dashed', direction: 'forward', points: [[110, 510], [410, 510]] },
    { id: 'LM05', name: '', style: 'dashed', direction: 'forward', points: [[120, 570], [410, 570]] },
    { id: 'LM06', name: '', style: 'solid', direction: 'forward', points: [[110, 150], [440, 150]] },
    { id: 'LM07', name: '', style: 'dashed', direction: 'forward', points: [[110, 120], [780, 120]] },
    { id: 'LM08', name: '', style: 'dashed', direction: 'forward', points: [[110, 180], [410, 180]] },
    { id: 'LM09', name: '', style: 'solid', direction: 'forward', points: [[500, 460], [500, 180]] },
    { id: 'LM10', name: '', style: 'solid', direction: 'forward', points: [[440, 460], [440, 150]] },
    { id: 'LM11', name: '', style: 'dashed', direction: 'forward', points: [[470, 460], [470, 150]] },
    { id: 'LM12', name: '', style: 'dashed', direction: 'forward', points: [[530, 460], [530, 220]] },
    { id: 'LM13', name: '', style: 'solid', direction: 'forward', points: [[500, 180], [720, 180]] },
    { id: 'LM14', name: '', style: 'dashed', direction: 'forward', points: [[470, 150], [740, 150]] },
    { id: 'LM15', name: '', style: 'solid', direction: 'forward', points: [[720, 180], [720, 220]] },
    { id: 'LM16', name: '', style: 'dashed', direction: 'forward', points: [[750, 150], [750, 460]] },
    { id: 'LM17', name: '', style: 'dashed', direction: 'forward', points: [[780, 120], [780, 460]] },
    { id: 'LM18', name: '', style: 'solid', direction: 'forward', points: [[820, 90], [820, 220]] },
    { id: 'LM19', name: '', style: 'solid', direction: 'forward', points: [[720, 510], [560, 510]] },
    { id: 'LM20', name: '', style: 'dashed', direction: 'forward', points: [[720, 480], [560, 480]] },
    { id: 'LM21', name: '', style: 'dashed', direction: 'forward', points: [[720, 540], [560, 540]] },
    { id: 'LM22', name: '', style: 'dashed', direction: 'forward', points: [[720, 570], [560, 570]] },
  ],
  crosswalks: [
    { id: 'CW01', width: 34, stripe_count: 6, points: [[20, 470], [110, 470]] },
    { id: 'CW02', width: 34, stripe_count: 6, points: [[110, 600], [110, 470]] },
    { id: 'CW03', width: 34, stripe_count: 6, points: [[190, 470], [270, 470]] },
    { id: 'CW04', width: 34, stripe_count: 6, points: [[410, 470], [410, 600]] },
    { id: 'CW05', width: 34, stripe_count: 6, points: [[560, 450], [410, 450]] },
    { id: 'CW06', width: 34, stripe_count: 6, points: [[560, 600], [560, 450]] },
    { id: 'CW07', width: 34, stripe_count: 6, points: [[720, 600], [720, 450]] },
    { id: 'CW08', width: 34, stripe_count: 6, points: [[820, 450], [720, 450]] },
    { id: 'CW09', width: 34, stripe_count: 6, points: [[190, 220], [190, 220]] },
    { id: 'CW10', width: 34, stripe_count: 6, points: [[190, 220], [270, 220]] },
    { id: 'CW11', width: 34, stripe_count: 6, points: [[110, 220], [20, 220]] },
    { id: 'CW12', width: 34, stripe_count: 6, points: [[110, 90], [110, 220]] },
    { id: 'CW13', width: 34, stripe_count: 6, points: [[820, 600], [820, 450]] },
    { id: 'CW14', width: 34, stripe_count: 6, points: [[720, 600], [820, 600]] },
    { id: 'CW15', width: 34, stripe_count: 6, points: [[410, 600], [560, 600]] },
    { id: 'CW16', width: 34, stripe_count: 6, points: [[110, 600], [20, 600]] },
  ],
  road_arrows: [
    { id: 'A02', x: 210, y: 350, angle: 90, size: 14 },
    { id: 'A04', x: 250, y: 350, angle: 270, size: 14 },
    { id: 'A06', x: 50, y: 350, angle: 90, size: 14 },
    { id: 'A07', x: 450, y: 320, angle: 90.2, size: 14 },
    { id: 'A08', x: 90, y: 350, angle: 270.2, size: 14 },
    { id: 'A09', x: 430, y: 320, angle: 90.9, size: 14 },
    { id: 'A10', x: 480, y: 320, angle: 90.9, size: 14 },
    { id: 'A11', x: 510, y: 320, angle: -90, size: 14 },
    { id: 'A12', x: 540, y: 320, angle: -90, size: 14 },
    { id: 'A13', x: 740, y: 310, angle: 89.8, size: 14 },
    { id: 'A14', x: 770, y: 310, angle: 89.8, size: 14 },
    { id: 'A15', x: 800, y: 310, angle: 90, size: 14 },
    { id: 'A16', x: 610, y: 160, angle: 0, size: 14 },
    { id: 'A17', x: 610, y: 130, angle: 0, size: 14 },
    { id: 'A18', x: 610, y: 110, angle: 0, size: 14 },
    { id: 'A19', x: 250, y: 110, angle: 0, size: 14 },
    { id: 'A20', x: 250, y: 130, angle: 0, size: 14 },
    { id: 'A21', x: 250, y: 160, angle: 0, size: 14 },
    { id: 'A22', x: 260, y: 500, angle: 180, size: 14 },
    { id: 'A23', x: 260, y: 530, angle: 180, size: 14 },
    { id: 'A24', x: 260, y: 550, angle: 0, size: 14 },
    { id: 'A25', x: 630, y: 470, angle: 180, size: 14 },
    { id: 'A26', x: 630, y: 490, angle: 180, size: 14 },
    { id: 'A27', x: 630, y: 520, angle: 0, size: 14 },
    { id: 'A28', x: 630, y: 550, angle: -0.2, size: 14 },
    { id: 'A29', x: 260, y: 580, angle: 0, size: 14 },
    { id: 'A30', x: 630, y: 580, angle: -0.2, size: 14 },
  ],
};

export default roadModelV8;
