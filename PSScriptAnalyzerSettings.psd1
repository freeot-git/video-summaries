@{
    IncludeDefaultRules = $true
    # A script's messages are for the person running it.
    ExcludeRules        = @('PSAvoidUsingWriteHost')
    Rules               = @{
        PSUseCompatibleSyntax = @{
            Enable         = $true
            TargetVersions = @('5.1', '7.4')
        }
    }
}
