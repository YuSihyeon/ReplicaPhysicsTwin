#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Bridge/MuJoCoBridgeTypes.h"
#include "MuJoCoBridgeDemoActor.generated.h"

class UMuJoCoStateReceiverComponent;
class UProceduralMeshComponent;
class USceneComponent;
class UStaticMeshComponent;

/** Visual-only Phase 3 box. Its transform comes from MuJoCo, never Chaos. */
UCLASS()
class REPLICAPHYSICSTWIN_API AMuJoCoBridgeDemoActor : public AActor
{
	GENERATED_BODY()

public:
	AMuJoCoBridgeDemoActor();

	/** Configure the visual proxy for a MuJoCo freejoint object before Play begins. */
	void ConfigureForObject(
		const FString& InObjectId,
		const FVector& FullSizeCm,
		const FLinearColor& Color,
		const FString& LocalVisualMeshPath,
		bool bOwnBridgeConnection = true,
		bool bInDeformable = false,
		int32 InClothGridCols = 0,
		int32 InClothGridRows = 0,
		const FVector& InClothLocalBoundsMinCm = FVector::ZeroVector,
		const FVector& InClothLocalBoundsMaxCm = FVector::ZeroVector);

	void ApplyMuJoCoState(const FMuJoCoObjectState& State);
	void SetSelected(bool bInSelected);
	bool IsSelected() const { return bSelected; }
	const FString& GetBridgeObjectId() const { return ObjectId; }
	const FMuJoCoObjectState& GetLatestState() const { return LatestState; }

	UStaticMeshComponent* GetVisualMesh() const { return VisualMesh; }
	UProceduralMeshComponent* GetSemanticVisualMesh() const { return SemanticVisualMesh; }
	UMuJoCoStateReceiverComponent* GetReceiver() const { return Receiver; }

private:
	UPROPERTY(VisibleAnywhere, Category = "MuJoCo Bridge")
	TObjectPtr<USceneComponent> SceneRoot;

	UPROPERTY(VisibleAnywhere, Category = "MuJoCo Bridge")
	TObjectPtr<UStaticMeshComponent> VisualMesh;

	UPROPERTY(VisibleAnywhere, Category = "MuJoCo Bridge")
	TObjectPtr<UProceduralMeshComponent> SemanticVisualMesh;

	UPROPERTY(VisibleAnywhere, Category = "MuJoCo Bridge")
	TObjectPtr<UMuJoCoStateReceiverComponent> Receiver;

	UPROPERTY(VisibleAnywhere, Category = "MuJoCo Bridge")
	FString ObjectId;

	FMuJoCoObjectState LatestState;
	bool bSelected = false;
	bool bDeformable = false;
	int32 ClothGridCols = 0;
	int32 ClothGridRows = 0;
	FVector ClothLocalBoundsMinCm = FVector::ZeroVector;
	FVector ClothLocalBoundsMaxCm = FVector::ZeroVector;
	TArray<FVector> SemanticVertices;
	TArray<FVector> SemanticNormals;
	TArray<int32> SemanticTriangles;
	TArray<FColor> SemanticVertexColors;

	bool LoadLocalVisualMesh(const FString& SourceMeshPath, const FLinearColor& Color);
	void UpdateDeformableMesh(const TArray<FVector>& DeformedVerticesM);
};
