import roadModelV8Json from '../../../testdata/v8/road_model_edited (3).json';

type PointTuple = [number, number];

export interface RoadModelV8 {
  metadata: {
    name: string;
    coordinate_system: string;
    image_width: number;
    image_height: number;
    origin: string;
    x_axis: string;
    y_axis: string;
    source_image?: string;
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
  lanes: {
    id: string;
    road_id: string;
    travel: string;
    index: number;
    confidence: number;
  }[];
  lane_markings: {
    id: string;
    name?: string;
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

const roadModelV8 = roadModelV8Json as RoadModelV8;

export default roadModelV8;
