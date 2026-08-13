using UnrealBuildTool;

public class ReplicaPhysicsTwinEditorTarget : TargetRules
{
	public ReplicaPhysicsTwinEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V6;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_7;
		ExtraModuleNames.Add("ReplicaPhysicsTwin");
	}
}
