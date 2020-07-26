import { XYGlyph, XYGlyphView, XYGlyphData } from "./xy_glyph";
import { PointGeometry } from "../../core/geometry";
import { LineVector, FillVector } from "../../core/property_mixins";
import { Arrayable, Rect } from "../../core/types";
import { Line, Fill } from "../../core/visuals";
import * as p from "../../core/properties";
import { Context2d } from "../../core/util/canvas";
import { Selection } from "../selections/selection";
export interface AnnularWedgeData extends XYGlyphData {
    _inner_radius: Arrayable<number>;
    _outer_radius: Arrayable<number>;
    _start_angle: Arrayable<number>;
    _end_angle: Arrayable<number>;
    _angle: Arrayable<number>;
    sinner_radius: Arrayable<number>;
    souter_radius: Arrayable<number>;
    max_inner_radius: number;
    max_outer_radius: number;
}
export interface AnnularWedgeView extends AnnularWedgeData {
}
export declare class AnnularWedgeView extends XYGlyphView {
    model: AnnularWedge;
    visuals: AnnularWedge.Visuals;
    protected _map_data(): void;
    protected _render(ctx: Context2d, indices: number[], { sx, sy, _start_angle, _angle, sinner_radius, souter_radius }: AnnularWedgeData): void;
    protected _hit_point(geometry: PointGeometry): Selection;
    draw_legend_for_index(ctx: Context2d, bbox: Rect, index: number): void;
    private _scenterxy;
    scenterx(i: number): number;
    scentery(i: number): number;
}
export declare namespace AnnularWedge {
    type Attrs = p.AttrsOf<Props>;
    type Props = XYGlyph.Props & {
        direction: p.Direction;
        inner_radius: p.DistanceSpec;
        outer_radius: p.DistanceSpec;
        start_angle: p.AngleSpec;
        end_angle: p.AngleSpec;
    } & Mixins;
    type Mixins = LineVector & FillVector;
    type Visuals = XYGlyph.Visuals & {
        line: Line;
        fill: Fill;
    };
}
export interface AnnularWedge extends AnnularWedge.Attrs {
}
export declare class AnnularWedge extends XYGlyph {
    properties: AnnularWedge.Props;
    __view_type__: AnnularWedgeView;
    constructor(attrs?: Partial<AnnularWedge.Attrs>);
    static init_AnnularWedge(): void;
}
