import { type VariantProps } from "class-variance-authority";
declare const badgeVariants: (props?: ({
    variant?: "neutral" | "success" | "warning" | "info" | "danger" | null | undefined;
} & import("class-variance-authority/types").ClassProp) | undefined) => string;
type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>;
export declare function Badge({ className, variant, ...props }: BadgeProps): import("react/jsx-runtime").JSX.Element;
export {};
