package poller

// GraphQL texts (G§1.1). Differences from the Python engine, all additive: cross-repo
// `repository{nameWithOwner}` on parent, sub-issues, blockers and closing references, and
// the separate PROJECTS query for Projects v2 Status.

const prFields = `number url isDraft state mergedAt headRefName headRefOid reviewDecision mergeable statusCheckRollup { state }`

const prOpenFields = prFields + `
      latestOpinionatedReviews(first: 20) { nodes { state author { login } } }
      checks: statusCheckRollup { contexts(first: 1) { totalCount } }
      reviewThreads(first: 100) { nodes { isResolved isOutdated } }`

const issueNode = `
        number title state
        labels(first: 100) { nodes { name } }
        parent { number repository { nameWithOwner } }
        subIssues(first: 50) { nodes { number title state repository { nameWithOwner } } }
        blockedBy(first: 100) { nodes { number state repository { nameWithOwner } } }
        closedByPullRequestsReferences(first: 5, includeClosedPrs: true) { nodes { ` + prFields + ` } }
`

// MaxIssuePages is how many pages of 100 open issues one full fetch reads.
const MaxIssuePages = 5

const issuesPageQuery = `
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, after: $after, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { ` + issueNode + ` }
    }
  }
  rateLimit { cost remaining resetAt }
}
`

const fullQuery = `
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { ` + issueNode + ` }
    }
    closedEpics: issues(states: CLOSED, labels: ["epic"], first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number labels(first: 20) { nodes { name } } subIssues(first: 50) { nodes { number title state repository { nameWithOwner } } } }
    }
    mergedPrs: pullRequests(states: MERGED, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes {
        number title url mergedAt headRefName headRefOid body
        closingIssuesReferences(first: 10) { nodes { number parent { number repository { nameWithOwner } } } }
      }
    }
    openPrs: pullRequests(states: OPEN, first: 50, orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { title body ` + prOpenFields + ` closingIssuesReferences(first: 10) { nodes { number } } }
    }
  }
  rateLimit { cost remaining resetAt }
}
`

// probeQuery: what changes when the board would: any issue or PR touched, an open PR's CI,
// conflict or review state. 1 point.
const probeQuery = `
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    issues(first: 1, orderBy: {field: UPDATED_AT, direction: DESC}) { totalCount nodes { updatedAt } }
    pullRequests(first: 1, orderBy: {field: UPDATED_AT, direction: DESC}) { totalCount nodes { updatedAt } }
    openPrs: pullRequests(states: OPEN, first: 50) {
      nodes { number mergeable reviewDecision statusCheckRollup { state } }
    }
  }
  rateLimit { cost remaining resetAt }
}
`

// projectsQuery reads the Projects v2 "Status" single-select of each open issue. It is a separate
// call so a token without the read:project scope (or a repo with no project) cannot fail the main
// query; the statuses are then derived (G§3 mapping).
const projectsQuery = `
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, after: $after, orderBy: {field: CREATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        projectItems(first: 5) { nodes { fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } } } }
      }
    }
  }
  rateLimit { cost remaining resetAt }
}
`
