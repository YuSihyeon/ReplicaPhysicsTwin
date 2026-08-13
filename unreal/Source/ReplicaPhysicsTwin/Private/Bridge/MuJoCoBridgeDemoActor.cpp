#include "Bridge/MuJoCoBridgeDemoActor.h"

#include "Bridge/ReplicaMeshFormat.h"
#include "Bridge/MuJoCoStateReceiverComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Components/SceneComponent.h"
#include "Components/PrimitiveComponent.h"
#include "ProceduralMeshComponent.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "UObject/ConstructorHelpers.h"

AMuJoCoBridgeDemoActor::AMuJoCoBridgeDemoActor()
{
	PrimaryActorTick.bCanEverTick = false;

	SceneRoot = CreateDefaultSubobject<USceneComponent>(TEXT("SceneRoot"));
	RootComponent = SceneRoot;

	VisualMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("VisualMesh"));
	VisualMesh->SetupAttachment(SceneRoot);
	VisualMesh->SetMobility(EComponentMobility::Movable);
	VisualMesh->SetSimulatePhysics(false);
	VisualMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	VisualMesh->SetRelativeScale3D(FVector(0.1f));

	SemanticVisualMesh = CreateDefaultSubobject<UProceduralMeshComponent>(TEXT("SemanticVisualMesh"));
	SemanticVisualMesh->SetupAttachment(SceneRoot);
	SemanticVisualMesh->SetMobility(EComponentMobility::Movable);
	SemanticVisualMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	SemanticVisualMesh->SetRelativeTransform(FTransform::Identity);
	SemanticVisualMesh->SetVisibility(false);

	static ConstructorHelpers::FObjectFinder<UStaticMesh> CubeMesh(TEXT("/Engine/BasicShapes/Cube.Cube"));
	if (CubeMesh.Succeeded())
	{
		VisualMesh->SetStaticMesh(CubeMesh.Object);
	}
	UMaterialInterface* BaseMaterial = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
	if (BaseMaterial != nullptr)
	{
		if (UMaterialInstanceDynamic* DynamicMaterial = UMaterialInstanceDynamic::Create(BaseMaterial, this))
		{
			DynamicMaterial->SetVectorParameterValue(TEXT("Color"), FLinearColor(0.1f, 0.65f, 1.0f, 1.0f));
			VisualMesh->SetMaterial(0, DynamicMaterial);
		}
	}

	Receiver = CreateDefaultSubobject<UMuJoCoStateReceiverComponent>(TEXT("MuJoCoStateReceiver"));
}

void AMuJoCoBridgeDemoActor::ConfigureForObject(
	const FString& InObjectId,
	const FVector& FullSizeCm,
	const FLinearColor& Color,
	const FString& LocalVisualMeshPath,
	bool bOwnBridgeConnection,
	bool bInDeformable,
	int32 InClothGridCols,
	int32 InClothGridRows,
	const FVector& InClothLocalBoundsMinCm,
	const FVector& InClothLocalBoundsMaxCm)
{
	ObjectId = InObjectId;
	bDeformable = bInDeformable;
	ClothGridCols = InClothGridCols;
	ClothGridRows = InClothGridRows;
	ClothLocalBoundsMinCm = InClothLocalBoundsMinCm;
	ClothLocalBoundsMaxCm = InClothLocalBoundsMaxCm;
	if (Receiver != nullptr)
	{
		Receiver->ObjectId = InObjectId;
		Receiver->bAutoConnect = bOwnBridgeConnection;
	}
	if (VisualMesh != nullptr)
	{
		// The engine BasicShapes cube is 100 cm on each side.
		VisualMesh->SetRelativeScale3D(FullSizeCm / 100.0f);
		if (UMaterialInterface* BaseMaterial = LoadObject<UMaterialInterface>(
			nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial")))
		{
			if (UMaterialInstanceDynamic* DynamicMaterial = UMaterialInstanceDynamic::Create(BaseMaterial, this))
			{
				DynamicMaterial->SetVectorParameterValue(TEXT("Color"), Color);
				VisualMesh->SetMaterial(0, DynamicMaterial);
			}
		}
		VisualMesh->SetRenderCustomDepth(true);
		VisualMesh->SetCustomDepthStencilValue(252);
	}

	const bool bSemanticMeshLoaded = LoadLocalVisualMesh(LocalVisualMeshPath, Color);
	if (SemanticVisualMesh != nullptr)
	{
		// RPTMESH vertices are already in Unreal centimetres.  Keep the visual
		// mesh in the actor's local frame so only the MuJoCo pose drives it.
		SemanticVisualMesh->SetRelativeTransform(FTransform::Identity);
		SemanticVisualMesh->SetVisibility(bSemanticMeshLoaded);
		SemanticVisualMesh->SetRenderCustomDepth(bSemanticMeshLoaded);
		SemanticVisualMesh->SetCustomDepthStencilValue(252);
	}
	if (VisualMesh != nullptr)
	{
		VisualMesh->SetVisibility(!bSemanticMeshLoaded);
	}
}

void AMuJoCoBridgeDemoActor::ApplyMuJoCoState(const FMuJoCoObjectState& State)
{
	LatestState = State;
	if (bDeformable && State.bHasDeformedVertices)
	{
		// Flex vertices arrive in world meters.  The high-resolution source mesh
		// is updated in world centimeters instead of being moved as one rigid
		// actor, so MuJoCo's bending is visible in Unreal.
		SetActorTransform(FTransform::Identity, false, nullptr, ETeleportType::TeleportPhysics);
		UpdateDeformableMesh(State.DeformedVerticesM);
	}
	else
	{
		SetActorTransform(State.ToUnrealTransform(), false, nullptr, ETeleportType::TeleportPhysics);
	}
	if (UPrimitiveComponent* Primitive = FindComponentByClass<UPrimitiveComponent>())
	{
		// Unreal is a visual receiver only. Collision and integration remain in MuJoCo.
		Primitive->SetSimulatePhysics(false);
		Primitive->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	}
}

void AMuJoCoBridgeDemoActor::UpdateDeformableMesh(const TArray<FVector>& DeformedVerticesM)
{
	if (SemanticVisualMesh == nullptr
		|| ClothGridCols < 2
		|| ClothGridRows < 2
		|| DeformedVerticesM.Num() != ClothGridCols * ClothGridRows
		|| SemanticVertices.Num() == 0
		|| SemanticTriangles.Num() == 0)
	{
		return;
	}

	const float Width = FMath::Max(ClothLocalBoundsMaxCm.X - ClothLocalBoundsMinCm.X, 0.01f);
	const float Height = FMath::Max(ClothLocalBoundsMaxCm.Z - ClothLocalBoundsMinCm.Z, 0.01f);
	TArray<FVector> UpdatedVertices;
	UpdatedVertices.SetNumUninitialized(SemanticVertices.Num());
	for (int32 VertexIndex = 0; VertexIndex < SemanticVertices.Num(); ++VertexIndex)
	{
		const FVector& LocalVertex = SemanticVertices[VertexIndex];
		const float U = FMath::Clamp((LocalVertex.X - ClothLocalBoundsMinCm.X) / Width, 0.0f, 1.0f);
		const float V = FMath::Clamp((LocalVertex.Z - ClothLocalBoundsMinCm.Z) / Height, 0.0f, 1.0f);
		const float GridX = U * static_cast<float>(ClothGridCols - 1);
		const float GridY = V * static_cast<float>(ClothGridRows - 1);
		const int32 X0 = FMath::Min(FMath::FloorToInt(GridX), ClothGridCols - 2);
		const int32 Y0 = FMath::Min(FMath::FloorToInt(GridY), ClothGridRows - 2);
		const int32 X1 = X0 + 1;
		const int32 Y1 = Y0 + 1;
		const float FX = FMath::Clamp(GridX - static_cast<float>(X0), 0.0f, 1.0f);
		const float FY = FMath::Clamp(GridY - static_cast<float>(Y0), 0.0f, 1.0f);
		const auto Sample = [&DeformedVerticesM, this](int32 X, int32 Y)
		{
			const int32 Index = X * ClothGridRows + Y;
			return DeformedVerticesM[Index] * 100.0f;
		};
		const FVector P00 = Sample(X0, Y0);
		const FVector P10 = Sample(X1, Y0);
		const FVector P01 = Sample(X0, Y1);
		const FVector P11 = Sample(X1, Y1);
		const FVector DeformedSurface = FMath::Lerp(FMath::Lerp(P00, P10, FX), FMath::Lerp(P01, P11, FX), FY);
		// Keep the source scan's local depth instead of collapsing the whole
		// garment into a mathematically flat sheet.  MuJoCo supplies the cloth
		// surface motion; the source Y offset preserves sleeves/folds/volume in
		// the Unreal presentation mesh.
		UpdatedVertices[VertexIndex] = DeformedSurface + FVector(0.0f, LocalVertex.Y, 0.0f);
	}

	TArray<FVector> UpdatedNormals;
	UpdatedNormals.Init(FVector::ZeroVector, UpdatedVertices.Num());
	for (int32 Index = 0; Index + 2 < SemanticTriangles.Num(); Index += 3)
	{
		const int32 AIndex = SemanticTriangles[Index];
		const int32 BIndex = SemanticTriangles[Index + 1];
		const int32 CIndex = SemanticTriangles[Index + 2];
		if (!UpdatedVertices.IsValidIndex(AIndex) || !UpdatedVertices.IsValidIndex(BIndex) || !UpdatedVertices.IsValidIndex(CIndex))
		{
			continue;
		}
		const FVector FaceNormal = FVector::CrossProduct(
			UpdatedVertices[BIndex] - UpdatedVertices[AIndex],
			UpdatedVertices[CIndex] - UpdatedVertices[AIndex]);
		UpdatedNormals[AIndex] += FaceNormal;
		UpdatedNormals[BIndex] += FaceNormal;
		UpdatedNormals[CIndex] += FaceNormal;
	}
	for (FVector& Normal : UpdatedNormals)
	{
		Normal = Normal.IsNearlyZero() ? FVector::UpVector : Normal.GetSafeNormal();
	}

	TArray<FVector2D> UV0;
	TArray<FProcMeshTangent> Tangents;
	SemanticVisualMesh->UpdateMeshSection(0, UpdatedVertices, UpdatedNormals, UV0, SemanticVertexColors, Tangents);
}

void AMuJoCoBridgeDemoActor::SetSelected(bool bInSelected)
{
	bSelected = bInSelected;
	if (VisualMesh != nullptr)
	{
		VisualMesh->SetRenderCustomDepth(true);
		VisualMesh->SetCustomDepthStencilValue(bSelected ? 253 : 252);
	}
	if (SemanticVisualMesh != nullptr)
	{
		SemanticVisualMesh->SetRenderCustomDepth(true);
		SemanticVisualMesh->SetCustomDepthStencilValue(bSelected ? 253 : 252);
	}
}

bool AMuJoCoBridgeDemoActor::LoadLocalVisualMesh(const FString& SourceMeshPath, const FLinearColor& Color)
{
	if (SemanticVisualMesh == nullptr || SourceMeshPath.IsEmpty())
	{
		return false;
	}

	const FString AbsolutePath = FPaths::IsRelative(SourceMeshPath)
		? FPaths::ConvertRelativePathToFull(FPaths::ProjectDir(), SourceMeshPath)
		: FPaths::ConvertRelativePathToFull(SourceMeshPath);
	TArray<uint8> Bytes;
	if (!FFileHelper::LoadFileToArray(Bytes, *AbsolutePath))
	{
		UE_LOG(LogMuJoCoBridge, Warning, TEXT("Semantic visual mesh could not be loaded: %s"), *AbsolutePath);
		return false;
	}
	if (Bytes.Num() >= 8 && FMemory::Memcmp(Bytes.GetData(), "RPTMESH2", 8) == 0)
	{
		return ReplicaMeshFormat::LoadRPTMesh2(
			SemanticVisualMesh,
			Bytes,
			AbsolutePath,
			Color,
			&SemanticVertices,
			&SemanticNormals,
			&SemanticTriangles,
			&SemanticVertexColors);
	}

	constexpr int32 HeaderBytes = 16;
	if (Bytes.Num() < HeaderBytes || FMemory::Memcmp(Bytes.GetData(), "RPTMESH1", 8) != 0)
	{
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Invalid semantic visual mesh header: %s"), *AbsolutePath);
		return false;
	}

	uint32 VertexCount = 0;
	uint32 IndexCount = 0;
	FMemory::Memcpy(&VertexCount, Bytes.GetData() + 8, sizeof(uint32));
	FMemory::Memcpy(&IndexCount, Bytes.GetData() + 12, sizeof(uint32));
	const uint64 ExpectedBytes = static_cast<uint64>(HeaderBytes)
		+ static_cast<uint64>(VertexCount) * sizeof(float) * 3 * 2
		+ static_cast<uint64>(IndexCount) * sizeof(uint32);
	if (VertexCount == 0 || IndexCount == 0 || (IndexCount % 3) != 0 || ExpectedBytes != static_cast<uint64>(Bytes.Num()))
	{
		UE_LOG(LogMuJoCoBridge, Error, TEXT("Invalid semantic visual mesh payload: %s vertices=%u indices=%u"), *AbsolutePath, VertexCount, IndexCount);
		return false;
	}

	TArray<FVector> Vertices;
	TArray<FVector> Normals;
	TArray<int32> Triangles;
	Vertices.SetNumUninitialized(static_cast<int32>(VertexCount));
	Normals.SetNumUninitialized(static_cast<int32>(VertexCount));
	Triangles.SetNumUninitialized(static_cast<int32>(IndexCount));
	const uint8* Cursor = Bytes.GetData() + HeaderBytes;
	for (uint32 Index = 0; Index < VertexCount; ++Index)
	{
		float Values[3];
		FMemory::Memcpy(Values, Cursor, sizeof(Values));
		Cursor += sizeof(Values);
		Vertices[static_cast<int32>(Index)] = FVector(Values[0], Values[1], Values[2]);
	}
	for (uint32 Index = 0; Index < VertexCount; ++Index)
	{
		float Values[3];
		FMemory::Memcpy(Values, Cursor, sizeof(Values));
		Cursor += sizeof(Values);
		Normals[static_cast<int32>(Index)] = FVector(Values[0], Values[1], Values[2]);
	}
	for (uint32 Index = 0; Index < IndexCount; ++Index)
	{
		uint32 VertexIndex = 0;
		FMemory::Memcpy(&VertexIndex, Cursor, sizeof(uint32));
		Cursor += sizeof(uint32);
		if (VertexIndex >= VertexCount)
		{
			UE_LOG(LogMuJoCoBridge, Error, TEXT("Semantic visual mesh index out of range: %u >= %u"), VertexIndex, VertexCount);
			return false;
		}
		Triangles[static_cast<int32>(Index)] = static_cast<int32>(VertexIndex);
	}

	// The Replica semantic PLY normals are scan normals and can contain sharp
	// discontinuities or stale values after face filtering.  Rebuild smooth
	// area-weighted normals from the actual triangles so the silhouette and
	// shading remain readable in Unreal.
	Normals.Init(FVector::ZeroVector, Vertices.Num());
	for (uint32 Index = 0; Index + 2 < IndexCount; Index += 3)
	{
		const FVector& A = Vertices[Triangles[static_cast<int32>(Index)]];
		const FVector& B = Vertices[Triangles[static_cast<int32>(Index + 1)]];
		const FVector& C = Vertices[Triangles[static_cast<int32>(Index + 2)]];
		const FVector FaceNormal = FVector::CrossProduct(B - A, C - A);
		if (FaceNormal.SizeSquared() <= KINDA_SMALL_NUMBER)
		{
			continue;
		}
		Normals[Triangles[static_cast<int32>(Index)]] += FaceNormal;
		Normals[Triangles[static_cast<int32>(Index + 1)]] += FaceNormal;
		Normals[Triangles[static_cast<int32>(Index + 2)]] += FaceNormal;
	}
	for (FVector& Normal : Normals)
	{
		Normal = Normal.IsNearlyZero() ? FVector::UpVector : Normal.GetSafeNormal();
	}

	TArray<FVector2D> UV0;
	TArray<FColor> VertexColors;
	VertexColors.Init(Color.ToFColor(true), Vertices.Num());
	TArray<FProcMeshTangent> Tangents;
	SemanticVisualMesh->ClearAllMeshSections();
	SemanticVisualMesh->CreateMeshSection(
		0,
		Vertices,
		Triangles,
		Normals,
		UV0,
		VertexColors,
		Tangents,
		false);
	SemanticVertices = Vertices;
	SemanticNormals = Normals;
	SemanticTriangles = Triangles;
	SemanticVertexColors = VertexColors;
	UMaterialInterface* VertexColorMaterial = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Engine/EngineDebugMaterials/VertexColorMaterial.VertexColorMaterial"));
	UMaterialInterface* ColorMaterial = LoadObject<UMaterialInterface>(
		nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial"));
	if (VertexColorMaterial != nullptr)
	{
		// The procedural mesh already contains a uniform per-object vertex
		// color.  This path is deterministic in standalone and does not depend
		// on a material parameter or a baked lightmap.
		SemanticVisualMesh->SetMaterial(0, VertexColorMaterial);
	}
	else if (ColorMaterial != nullptr)
	{
		if (UMaterialInstanceDynamic* DynamicMaterial = UMaterialInstanceDynamic::Create(ColorMaterial, this))
		{
			DynamicMaterial->SetVectorParameterValue(TEXT("Color"), Color);
			DynamicMaterial->SetScalarParameterValue(TEXT("Roughness"), 0.78f);
			SemanticVisualMesh->SetMaterial(0, DynamicMaterial);
		}
	}
	SemanticVisualMesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	SemanticVisualMesh->SetCastShadow(true);
	UE_LOG(LogMuJoCoBridge, Log, TEXT("Loaded semantic visual mesh: %s vertices=%u triangles=%u color=(%.2f,%.2f,%.2f)"),
		*AbsolutePath, VertexCount, IndexCount / 3, Color.R, Color.G, Color.B);
	return true;
}
