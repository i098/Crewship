# Split a dotenv file (read with jq -Rs) for Secrets Store, which holds at most 65,536 bytes
# per secret and 100 secrets per account. chunks: the whole file base64-encoded, cut every
# `limit` characters; limit is a multiple of 4, so the chunks join into one base64 string
# that decodes to the exact file. vars: each NAME's last assignment (the one `source` keeps),
# without one surrounding pair of matching quotes.
def limit: 65536;

{chunks: [@base64 | range(0; length; limit) as $i | .[$i:$i + limit]],
 vars: (reduce (split("\n")[] | capture("^(?<name>[A-Za-z_][A-Za-z0-9_]*)=(?<value>.*)$")) as $v
   ({}; .[$v.name] = ($v.value
     | if length > 1 and (.[:1] == "\"" or .[:1] == "'") and .[-1:] == .[:1]
       then .[1:-1] else . end)))}
