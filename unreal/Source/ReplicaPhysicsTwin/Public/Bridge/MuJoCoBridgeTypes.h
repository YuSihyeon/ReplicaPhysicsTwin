#pragma once

#include "CoreMinimal.h"
#include "MuJoCoBridgeTypes.generated.h"

USTRUCT(BlueprintType)
struct REPLICAPHYSICSTWIN_API FMuJoCoContact
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FString OtherId;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FVector ForceN = FVector::ZeroVector;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	double DistanceM = 0.0;
};

USTRUCT(BlueprintType)
struct REPLICAPHYSICSTWIN_API FMuJoCoPhysicalProperties
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FVector SizeM = FVector::ZeroVector;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	double MassKg = 0.0;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FVector InertiaDiagonalKgM2 = FVector::ZeroVector;

	/** X/Y/Z = sliding/torsional/rolling friction. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FVector Friction = FVector::ZeroVector;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	bool bMovable = false;
};

/** One MuJoCo object state expressed in wire units (meters, wxyz quaternion). */
USTRUCT(BlueprintType)
struct REPLICAPHYSICSTWIN_API FMuJoCoObjectState
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FString ObjectId;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	int32 SourceObjectId = -1;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	bool bHasSourceObjectId = false;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FString Role;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FVector PositionM = FVector::ZeroVector;

	/** Stored as an Unreal quaternion after parsing the MuJoCo wxyz wire order. */
	FQuat Rotation = FQuat::Identity;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FVector LinearVelocityMps = FVector::ZeroVector;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FVector AngularVelocityRps = FVector::ZeroVector;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	TArray<FMuJoCoContact> Contacts;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FMuJoCoPhysicalProperties Properties;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	bool bHasProperties = false;

	/** World-space MuJoCo flex vertices for a deformable object, in meters. */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	TArray<FVector> DeformedVerticesM;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	bool bHasDeformedVertices = false;

	FTransform ToUnrealTransform() const;
};

/** Validated state envelope received from the MuJoCo bridge. */
USTRUCT(BlueprintType)
struct REPLICAPHYSICSTWIN_API FMuJoCoStateMessage
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	int64 Seq = -1;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	int32 SchemaVersion = 0;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	double SimTime = 0.0;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FString SceneId;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	FString PhysicsAuthority;

	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "MuJoCo")
	TArray<FMuJoCoObjectState> Objects;

	static bool ParseLine(const FString& JsonLine, FMuJoCoStateMessage& OutMessage, FString* OutError = nullptr);
	static bool ShouldApplySequence(int64 LastAppliedSeq, int64 CandidateSeq);
};
