package jev

import "context"

const routeQuestion = "Which route fits this request in a developer tool: a new feature that needs a product spec, one small change, a bug report, or unclear?"

var routeOptions = map[string]string{
	"feature": "a new capability that needs a product spec: several screens, rules or decisions",
	"small":   "one small, clear change to something that already works",
	"bug":     "something is broken: an error, crash, wrong output or a stack trace",
	"unclear": "too vague or mixed to tell",
}

// MinRouteP is the lowest probability at which a route answer selects a route.
const MinRouteP = 0.4

// RouteAnswer is the response of POST /api/jev/route. Route is set only when Status is ok;
// P is also set for unsure. Status is an Ask status or unsure.
type RouteAnswer struct {
	Route  *string  `json:"route"`
	P      *float64 `json:"p"`
	Status string   `json:"status"`
}

// Route classifies Create box text as feature, small or bug. It never errors; the point is
// neither cached nor counted against the ceiling.
func (c *Client) Route(ctx context.Context, text string) RouteAnswer {
	a := c.Ask(ctx, "route", "choice", routeQuestion, text, routeOptions, nil)
	if a.Status != "ok" {
		return RouteAnswer{Status: a.Status}
	}
	if _, known := routeOptions[a.Choice]; !known {
		return RouteAnswer{Status: "unreadable"}
	}
	p := a.P
	if a.Choice == "unclear" || p < MinRouteP {
		return RouteAnswer{P: &p, Status: "unsure"}
	}
	route := a.Choice
	return RouteAnswer{Route: &route, P: &p, Status: "ok"}
}
