declare module 'simpleheat' {
  export type SimpleHeatPoint = [number, number, number];

  export interface SimpleHeat {
    data(data: SimpleHeatPoint[]): SimpleHeat;
    max(max: number): SimpleHeat;
    add(point: SimpleHeatPoint): SimpleHeat;
    clear(): SimpleHeat;
    radius(radius: number, blur?: number): SimpleHeat;
    resize(): void;
    gradient(gradient: Record<number, string>): SimpleHeat;
    draw(minOpacity?: number): SimpleHeat;
  }

  export default function simpleheat(canvas: HTMLCanvasElement | string): SimpleHeat;
}
