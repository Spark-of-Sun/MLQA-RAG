# OpenBao in local key mode (blueprint 12.10, R-59, task 3.7): the local stand-in for AWS KMS.
#
# Unlike dev mode, keys persist in the `openbao` volume, so encrypted rows stay readable across restarts; only
# `make db-reset` (which removes the volumes) destroys them, together with the data they protect. The server unseals
# itself with a static key from OPENBAO_UNSEAL_KEY and, on its first start, initializes itself: it creates the API
# token named by OPENBAO_TOKEN and mounts Transit (organization and platform CMKs) and KV v2 (recorded key states).
# Both values are generated into .env by `make setup` (when missing) and passed by name only; neither is in this file.
# Local and CI only: a production key store is AWS KMS (KMS_PROVIDER=aws).

ui           = false
api_addr     = "http://127.0.0.1:8200"
cluster_addr = "http://127.0.0.1:8201"

# Integrated storage, one node (OpenBao 2.x has no plain file backend).
storage "raft" {
  path    = "/openbao/file"
  node_id = "lmqa-local"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = true
}

seal "static" {
  current_key_id = "lmqa-local-1"
  current_key    = "env://OPENBAO_UNSEAL_KEY"
}

initialize "lmqa" {
  request "token" {
    operation = "update"
    path      = "auth/token/create-orphan"
    data = {
      id = {
        eval_type       = "string"
        eval_source     = "env"
        env_var         = "OPENBAO_TOKEN"
        require_present = true
      }
      policies     = ["root"]
      display_name = "lmqa-local"
    }
  }
  request "transit" {
    operation = "update"
    path      = "sys/mounts/transit"
    data = {
      type = "transit"
    }
  }
  request "kv" {
    operation = "update"
    path      = "sys/mounts/secret"
    data = {
      type    = "kv"
      options = {
        version = "2"
      }
    }
  }
}
