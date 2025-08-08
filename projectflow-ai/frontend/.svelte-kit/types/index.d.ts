type DynamicRoutes = {
	
};

type Layouts = {
	"/": undefined;
	"/login": undefined
};

export type RouteId = "/" | "/login";

export type RouteParams<T extends RouteId> = T extends keyof DynamicRoutes ? DynamicRoutes[T] : Record<string, never>;

export type LayoutParams<T extends RouteId> = Layouts[T] | Record<string, never>;

export type Pathname = "/" | "/login";

export type ResolvedPathname = `${"" | `/${string}`}${Pathname}`;

export type Asset = never;