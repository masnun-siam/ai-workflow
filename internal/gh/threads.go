package gh

import (
	"context"
	"encoding/json"
	"strconv"
	"strings"

	"github.com/masnun-siam/setu/internal/errs"
)

const threadsQuery = `
query($owner:String!,$repo:String!,$number:Int!,$cursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$number){
      reviewThreads(first:100, after:$cursor){
        pageInfo{ hasNextPage endCursor }
        nodes{
          id isResolved isOutdated path line
          comments(first:1){ nodes{ databaseId url body } }
        }
      }
    }
  }
}
`

const resolveMutation = `
mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){ thread{ id isResolved } } }
`

// Thread is one review thread, flattened. CommentID is the REST databaseId of its FIRST comment.
type Thread struct {
	NodeID     string
	IsResolved bool
	IsOutdated bool
	CommentID  int64
	URL, Path  string
	Line       *int
}

// MarshalJSON emits {node_id,is_resolved,is_outdated,comment_id,url,path,line}; a missing
// comment id, url or path is null.
func (t Thread) MarshalJSON() ([]byte, error) {
	o := struct {
		NodeID     string  `json:"node_id"`
		IsResolved bool    `json:"is_resolved"`
		IsOutdated bool    `json:"is_outdated"`
		CommentID  *int64  `json:"comment_id"`
		URL        *string `json:"url"`
		Path       *string `json:"path"`
		Line       *int    `json:"line"`
	}{NodeID: t.NodeID, IsResolved: t.IsResolved, IsOutdated: t.IsOutdated, Line: t.Line}
	if t.CommentID != 0 {
		o.CommentID = &t.CommentID
	}
	if t.URL != "" {
		o.URL = &t.URL
	}
	if t.Path != "" {
		o.Path = &t.Path
	}
	return json.Marshal(o)
}

type threadsPage struct {
	Data struct {
		Repository struct {
			PullRequest struct {
				ReviewThreads struct {
					PageInfo struct {
						HasNextPage bool   `json:"hasNextPage"`
						EndCursor   string `json:"endCursor"`
					} `json:"pageInfo"`
					Nodes []struct {
						ID         string `json:"id"`
						IsResolved bool   `json:"isResolved"`
						IsOutdated bool   `json:"isOutdated"`
						Path       string `json:"path"`
						Line       *int   `json:"line"`
						Comments   struct {
							Nodes []struct {
								DatabaseID int64  `json:"databaseId"`
								URL        string `json:"url"`
							} `json:"nodes"`
						} `json:"comments"`
					} `json:"nodes"`
				} `json:"reviewThreads"`
			} `json:"pullRequest"`
		} `json:"repository"`
	} `json:"data"`
}

// ListThreads returns every review thread of the PR, paging by cursor (100 per page).
// A failed call is errs.Upstream("could not read review threads: …").
func ListThreads(ctx context.Context, c Client, p PRRef) ([]Thread, error) {
	out := []Thread{}
	cursor := ""
	for {
		args := []string{"api", "graphql", "-f", "query=" + threadsQuery, "-f", "owner=" + p.Owner, "-f", "repo=" + p.Repo, "-F", "number=" + strconv.Itoa(p.N)}
		if cursor != "" {
			args = append(args, "-f", "cursor="+cursor)
		}
		var page threadsPage
		res, err := c.JSON(ctx, args, 0, &page)
		if err != nil {
			text := strings.TrimSpace(string(res.Stderr))
			if text == "" {
				text = strings.TrimSpace(string(res.Stdout))
			}
			return nil, errs.Upstream("could not read review threads: %s", trunc(text, 300))
		}
		block := page.Data.Repository.PullRequest.ReviewThreads
		for _, n := range block.Nodes {
			t := Thread{NodeID: n.ID, IsResolved: n.IsResolved, IsOutdated: n.IsOutdated, Path: n.Path, Line: n.Line}
			if len(n.Comments.Nodes) > 0 {
				t.CommentID, t.URL = n.Comments.Nodes[0].DatabaseID, n.Comments.Nodes[0].URL
			}
			out = append(out, t)
		}
		if !block.PageInfo.HasNextPage {
			return out, nil
		}
		cursor = block.PageInfo.EndCursor
	}
}

// ThreadForComment is the thread whose first comment has this REST id. id may be an int, int64 or
// a numeric string; anything else matches nothing.
func ThreadForComment(ts []Thread, id any) (Thread, bool) {
	var want int64
	switch v := id.(type) {
	case int:
		want = int64(v)
	case int64:
		want = v
	case string:
		n, err := strconv.ParseInt(strings.TrimSpace(v), 10, 64)
		if err != nil {
			return Thread{}, false
		}
		want = n
	default:
		return Thread{}, false
	}
	for _, t := range ts {
		if t.CommentID == want {
			return t, true
		}
	}
	return Thread{}, false
}

// ResolveThread resolves one thread by node id. The error text is at most 200 chars.
func ResolveThread(ctx context.Context, c Client, nodeID string) error {
	var data struct {
		Errors []json.RawMessage `json:"errors"`
		Data   struct {
			Resolve struct {
				Thread struct {
					IsResolved bool `json:"isResolved"`
				} `json:"thread"`
			} `json:"resolveReviewThread"`
		} `json:"data"`
	}
	res, err := c.JSON(ctx, []string{"api", "graphql", "-f", "query=" + resolveMutation, "-f", "id=" + nodeID}, 0, &data)
	if err != nil {
		return errs.Upstream("%s", trunc(strings.TrimSpace(string(res.Stderr)), 200))
	}
	if len(data.Errors) > 0 {
		return errs.Upstream("%s", trunc(strings.TrimSpace(string(res.Stdout)), 200))
	}
	if !data.Data.Resolve.Thread.IsResolved {
		return errs.Upstream("")
	}
	return nil
}
