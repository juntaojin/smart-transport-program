const roadModelV5 = {
  "metadata": {
    "name": "学校沙盘道路模型 v0.2",
    "coordinate_system": "source_image_pixel_xy",
    "image_width": 954,
    "image_height": 740,
    "origin": "top_left",
    "x_axis": "right",
    "y_axis": "down",
    "source_image": "42198c7f-7b12-45c0-8baf-2a318eb8e537.png",
    "status": "updated_from_plan",
    "notes": "依据平面图重新建立，几何与拓扑较v0.1更可靠，仍需实测尺度校准。",
    "extent": {
      "width": 954,
      "height": 740
    }
  },
  "nodes": [
    {
      "id": "N01",
      "x": 25.401,
      "y": 94.318,
      "type": "boundary",
      "name": "西北入口",
      "confidence": 0.92
    },
    {
      "id": "N02",
      "x": 24.46,
      "y": 94.318,
      "type": "intersection",
      "name": "北侧中央路口",
      "confidence": 0.95
    },
    {
      "id": "N03",
      "x": 871.208,
      "y": 93.848,
      "type": "boundary",
      "name": "东北入口",
      "confidence": 0.9
    },
    {
      "id": "N04",
      "x": 192.399,
      "y": 221.33,
      "type": "junction",
      "name": "停车场北侧西口",
      "confidence": 0.9
    },
    {
      "id": "N14",
      "x": 22.579,
      "y": 682.808,
      "type": "intersection",
      "name": "中部主路西节点",
      "confidence": 0.95
    },
    {
      "id": "N15",
      "x": 870.738,
      "y": 678.574,
      "type": "intersection",
      "name": "中部主路东节点",
      "confidence": 0.95
    },
    {
      "id": "N16",
      "x": 873.56,
      "y": 594.37,
      "type": "intersection",
      "name": "东侧中部主路口",
      "confidence": 0.93
    },
    {
      "id": "N17",
      "x": 24.931,
      "y": 680.926,
      "type": "boundary",
      "name": "西南入口",
      "confidence": 0.9
    },
    {
      "id": "N18",
      "x": 803.939,
      "y": 477.236,
      "type": "boundary",
      "name": "南侧中央入口",
      "confidence": 0.9
    },
    {
      "id": "N19",
      "x": 874.971,
      "y": 681.867,
      "type": "boundary",
      "name": "东南入口",
      "confidence": 0.9
    },
    {
      "id": "N20",
      "x": 190.988,
      "y": 469.239,
      "type": "parking_access",
      "name": "停车场西南接入口",
      "confidence": 0.91
    },
    {
      "id": "N22",
      "x": 261.079,
      "y": 218.508,
      "type": "parking_loop",
      "name": "停车场中央环路北点",
      "confidence": 0.88
    },
    {
      "id": "N23",
      "x": 260.139,
      "y": 469.239,
      "type": "parking_loop",
      "name": "停车场中央环路南点",
      "confidence": 0.88
    },
    {
      "id": "N24",
      "x": 534.391,
      "y": 220.39,
      "type": "urban_loop",
      "name": "商务区环路西北点",
      "confidence": 0.88
    },
    {
      "id": "N25",
      "x": 719.264,
      "y": 221.801,
      "type": "urban_loop",
      "name": "商务区环路东北点",
      "confidence": 0.88
    },
    {
      "id": "N26",
      "x": 719.264,
      "y": 470.65,
      "type": "urban_loop",
      "name": "商务区环路东南点",
      "confidence": 0.9
    },
    {
      "id": "N27",
      "x": 535,
      "y": 470,
      "type": "urban_loop",
      "name": "商务区环路西南点",
      "confidence": 0.9
    },
    {
      "id": "N28",
      "x": 444.071,
      "y": 675.752,
      "type": "service_loop",
      "name": "消防医院环路西端",
      "confidence": 0.93
    },
    {
      "id": "N29",
      "x": 540.506,
      "y": 601.896,
      "type": "service_loop",
      "name": "消防医院环路东端",
      "confidence": 0.93
    },
    {
      "id": "N30",
      "x": 716.912,
      "y": 676.692,
      "type": "service_loop",
      "name": "消防医院环路东南端",
      "confidence": 0.93
    },
    {
      "id": "N31",
      "x": 115.721,
      "y": 604.248,
      "type": "service_loop",
      "name": "消防医院环路西南端",
      "confidence": 0.93
    },
    {
      "id": "N33",
      "x": 191.458,
      "y": 219.919,
      "type": "intersection",
      "name": "新路口",
      "confidence": 1
    },
    {
      "id": "N34",
      "x": 192.399,
      "y": 468.769,
      "type": "intersection",
      "name": "新路口",
      "confidence": 1
    },
    {
      "id": "N35",
      "x": 872.619,
      "y": 479.588,
      "type": "intersection",
      "name": "新路口",
      "confidence": 1
    }
  ],
  "roads": [
    {
      "id": "R02",
      "from": "N02",
      "to": "N03",
      "name": "北侧主路东段",
      "class": "arterial",
      "lanes": 4,
      "direction": "two_way",
      "confidence": 0.93,
      "centerline": [
        [
          24.46,
          94.318
        ],
        [
          871.208,
          93.848
        ]
      ]
    },
    {
      "id": "R03",
      "from": "N01",
      "to": "N17",
      "name": "西侧边界纵路",
      "class": "collector",
      "lanes": 2,
      "direction": "two_way",
      "confidence": 0.92,
      "centerline": [
        [
          25.401,
          94.318
        ],
        [
          22.579,
          682.808
        ]
      ]
    },
    {
      "id": "R04",
      "from": "N02",
      "to": "N18",
      "name": "中央纵向主路",
      "class": "arterial",
      "lanes": 4,
      "direction": "two_way",
      "confidence": 0.95,
      "centerline": [
        [
          866.504,
          224.153
        ],
        [
          802.527,
          224.623
        ],
        [
          803.939,
          477.236
        ]
      ]
    },
    {
      "id": "R05",
      "from": "N03",
      "to": "N19",
      "name": "东侧边界纵路",
      "class": "collector",
      "lanes": 2,
      "direction": "two_way",
      "confidence": 0.92,
      "centerline": [
        [
          871.208,
          93.848
        ],
        [
          874.971,
          681.867
        ]
      ]
    },
    {
      "id": "R11",
      "from": "N14",
      "to": "N15",
      "name": "中部东西主路中央段",
      "class": "arterial",
      "lanes": 4,
      "direction": "two_way",
      "confidence": 0.97,
      "centerline": [
        [
          22.579,
          682.808
        ],
        [
          870.738,
          678.574
        ]
      ]
    },
    {
      "id": "R12",
      "from": "N15",
      "to": "N16",
      "name": "中部东西主路东段",
      "class": "arterial",
      "lanes": 4,
      "direction": "two_way",
      "confidence": 0.96,
      "centerline": [
        [
          807.232,
          676.222
        ],
        [
          806.291,
          594.84
        ],
        [
          873.56,
          594.37
        ]
      ]
    },
    {
      "id": "R13",
      "from": "N04",
      "to": "N20",
      "name": "停车场西侧外环",
      "class": "parking_loop",
      "lanes": 1,
      "direction": "one_way",
      "confidence": 0.92,
      "centerline": [
        [
          192.399,
          221.33
        ],
        [
          111.017,
          221.801
        ],
        [
          113.369,
          469.239
        ],
        [
          190.988,
          469.239
        ]
      ]
    },
    {
      "id": "R15",
      "from": "N22",
      "to": "N23",
      "name": "停车场中央矩形环路西侧",
      "class": "parking_loop",
      "lanes": 1,
      "direction": "one_way",
      "confidence": 0.9,
      "centerline": [
        [
          261.079,
          218.508
        ],
        [
          260.139,
          469.239
        ]
      ]
    },
    {
      "id": "R16",
      "from": "N23",
      "to": "N22",
      "name": "停车场中央矩形环路东侧",
      "class": "parking_loop",
      "lanes": 1,
      "direction": "one_way",
      "confidence": 0.9,
      "centerline": [
        [
          260.139,
          469.239
        ],
        [
          445.012,
          470.18
        ],
        [
          444.071,
          217.567
        ],
        [
          261.079,
          218.508
        ]
      ]
    },
    {
      "id": "R19",
      "from": "N24",
      "to": "N25",
      "name": "商务区北侧弧段",
      "class": "urban_loop",
      "lanes": 2,
      "direction": "one_way_loop",
      "confidence": 0.9,
      "centerline": [
        [
          534.391,
          220.39
        ],
        [
          719.264,
          221.801
        ]
      ]
    },
    {
      "id": "R20",
      "from": "N25",
      "to": "N26",
      "name": "商务区东侧弯道",
      "class": "urban_loop",
      "lanes": 2,
      "direction": "one_way_loop",
      "confidence": 0.92,
      "centerline": [
        [
          719.264,
          221.801
        ],
        [
          719.264,
          470.65
        ]
      ]
    },
    {
      "id": "R21",
      "from": "N26",
      "to": "N27",
      "name": "商务区南侧直段",
      "class": "urban_loop",
      "lanes": 2,
      "direction": "one_way_loop",
      "confidence": 0.95,
      "centerline": [
        [
          719.264,
          470.65
        ],
        [
          535,
          470
        ]
      ]
    },
    {
      "id": "R22",
      "from": "N27",
      "to": "N24",
      "name": "商务区西侧弯道",
      "class": "urban_loop",
      "lanes": 2,
      "direction": "one_way_loop",
      "confidence": 0.9,
      "centerline": [
        [
          535,
          470
        ],
        [
          534.391,
          220.39
        ]
      ]
    },
    {
      "id": "R23",
      "from": "N28",
      "to": "N29",
      "name": "消防医院北侧服务路",
      "class": "service_loop",
      "lanes": 2,
      "direction": "two_way",
      "confidence": 0.95,
      "centerline": [
        [
          539.095,
          672.459
        ],
        [
          540.506,
          601.896
        ]
      ]
    },
    {
      "id": "R24",
      "from": "N29",
      "to": "N30",
      "name": "消防医院东侧弯段",
      "class": "service_loop",
      "lanes": 1,
      "direction": "one_way_loop",
      "confidence": 0.93,
      "centerline": [
        [
          539.095,
          600.015
        ],
        [
          716.441,
          599.544
        ],
        [
          716.912,
          676.692
        ]
      ]
    },
    {
      "id": "R25",
      "from": "N30",
      "to": "N31",
      "name": "消防医院南侧服务路",
      "class": "service_loop",
      "lanes": 1,
      "direction": "one_way_loop",
      "confidence": 0.93,
      "centerline": [
        [
          115.251,
          676.222
        ],
        [
          115.721,
          604.248
        ]
      ]
    },
    {
      "id": "R26",
      "from": "N31",
      "to": "N28",
      "name": "消防医院西侧弯段",
      "class": "service_loop",
      "lanes": 1,
      "direction": "one_way_loop",
      "confidence": 0.93,
      "centerline": [
        [
          115.721,
          604.248
        ],
        [
          444.071,
          605.189
        ],
        [
          444.071,
          675.752
        ]
      ]
    },
    {
      "id": "R31",
      "from": "N33",
      "to": "N34",
      "name": "N33-N34连接路",
      "class": "service",
      "lanes": 2,
      "direction": "two_way",
      "confidence": 1,
      "centerline": [
        [
          191.458,
          219.919
        ],
        [
          192.399,
          468.769
        ]
      ]
    },
    {
      "id": "R32",
      "from": "N35",
      "to": "N18",
      "name": "N35-N18连接路",
      "class": "service",
      "lanes": 2,
      "direction": "two_way",
      "confidence": 1,
      "centerline": [
        [
          872.619,
          479.588
        ],
        [
          802.057,
          477.707
        ]
      ]
    }
  ],
  "lanes": [
    {
      "id": "R02_F1",
      "road_id": "R02",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R02_F2",
      "road_id": "R02",
      "travel": "from_to",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R02_B1",
      "road_id": "R02",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R02_B2",
      "road_id": "R02",
      "travel": "to_from",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R03_F1",
      "road_id": "R03",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R03_B1",
      "road_id": "R03",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R04_F1",
      "road_id": "R04",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R04_F2",
      "road_id": "R04",
      "travel": "from_to",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R04_B1",
      "road_id": "R04",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R04_B2",
      "road_id": "R04",
      "travel": "to_from",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R05_F1",
      "road_id": "R05",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R05_B1",
      "road_id": "R05",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R11_F1",
      "road_id": "R11",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R11_F2",
      "road_id": "R11",
      "travel": "from_to",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R11_B1",
      "road_id": "R11",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R11_B2",
      "road_id": "R11",
      "travel": "to_from",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R12_F1",
      "road_id": "R12",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R12_F2",
      "road_id": "R12",
      "travel": "from_to",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R12_B1",
      "road_id": "R12",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R12_B2",
      "road_id": "R12",
      "travel": "to_from",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R13_L1",
      "road_id": "R13",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R15_L1",
      "road_id": "R15",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R16_L1",
      "road_id": "R16",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R19_L1",
      "road_id": "R19",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R19_L2",
      "road_id": "R19",
      "travel": "from_to",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R20_L1",
      "road_id": "R20",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R20_L2",
      "road_id": "R20",
      "travel": "from_to",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R21_L1",
      "road_id": "R21",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R21_L2",
      "road_id": "R21",
      "travel": "from_to",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R22_L1",
      "road_id": "R22",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R22_L2",
      "road_id": "R22",
      "travel": "from_to",
      "index": 2,
      "confidence": 1
    },
    {
      "id": "R23_F1",
      "road_id": "R23",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R23_B1",
      "road_id": "R23",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R24_L1",
      "road_id": "R24",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R25_L1",
      "road_id": "R25",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R26_L1",
      "road_id": "R26",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R31_F1",
      "road_id": "R31",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R31_B1",
      "road_id": "R31",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R32_F1",
      "road_id": "R32",
      "travel": "from_to",
      "index": 1,
      "confidence": 1
    },
    {
      "id": "R32_B1",
      "road_id": "R32",
      "travel": "to_from",
      "index": 1,
      "confidence": 1
    }
  ]
} as const;

export default roadModelV5;
