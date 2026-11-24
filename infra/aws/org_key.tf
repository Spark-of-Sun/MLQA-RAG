# Per-organization CMK module input (12.1). Organizations are created at runtime by the identity saga through
# lmqa_keys.AwsKmsProvider.create_key, which applies infra/keyguard/key-policy.json.tftpl rendered with the same
# variables; this resource exists for the drill organization only (G9.6), whose keys carry the `drill` tag.
variable "drill_org_id" {
  type    = string
  default = ""
}
resource "aws_kms_key" "drill_org" {
  count                   = var.drill_org_id == "" ? 0 : 1
  description             = "${local.name} drill organization ${var.drill_org_id}"
  multi_region            = true
  enable_key_rotation     = true
  deletion_window_in_days = 7
  tags                    = { drill = "true", org_id = var.drill_org_id }
  policy = templatefile("${path.module}/../keyguard/key-policy.json.tftpl", {
    account_id        = local.account_id
    org_id            = var.drill_org_id
    service_role_arns = jsonencode(local.service_roles)
    min_window_days   = 7
  })
}
